# feiyang-maintenance-scheduler 部署手册

将本工具部署到公网 HTTPS，并接入飞书工作台一键启动。

> 目标环境：Ubuntu 22.04 云服务器（阿里云 / 腾讯云 / 华为云通用）
> 项目路径：`/opt/feiyang-maintenance-scheduler`
> 仓库地址：https://github.com/JerryThe-cat/feiyang-maintenance-scheduler

---

## 一、准备清单

需先到位：

- [ ] 一台公网 IP 的云服务器（Ubuntu 22.04）
- [ ] 一个已实名备案的域名（飞书网页应用要求 HTTPS）
- [ ] 域名 **A 记录** 已指向服务器 IP
- [ ] 安全组 / 防火墙已放开 **22 / 80 / 443** 端口
- [ ] 飞书开发者后台已发布应用版本，`bitable:app` 权限已生效

---

## 二、一次性部署（服务器端）

### 1. 安装系统依赖

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip nginx certbot python3-certbot-nginx git
```

### 2. 克隆代码

```bash
sudo git clone https://github.com/JerryThe-cat/feiyang-maintenance-scheduler.git \
    /opt/feiyang-maintenance-scheduler
cd /opt/feiyang-maintenance-scheduler
```

### 3. 创建 Python 虚拟环境并安装依赖

```bash
sudo python3 -m venv .venv
sudo ./.venv/bin/pip install -r requirements.txt
```

### 4. 配置真实凭证

```bash
sudo tee /opt/feiyang-maintenance-scheduler/.env > /dev/null <<'EOF'
FEISHU_APP_ID=cli_xxxxxxxxxxxxxxxx
FEISHU_APP_SECRET=your_real_secret
FLASK_HOST=127.0.0.1
FLASK_PORT=5000
FLASK_DEBUG=0
EOF
sudo chmod 600 /opt/feiyang-maintenance-scheduler/.env
```

### 5. 准备日志目录与权限

```bash
sudo mkdir -p /var/log/feiyang-maintenance-scheduler
sudo chown -R www-data:www-data \
    /var/log/feiyang-maintenance-scheduler \
    /opt/feiyang-maintenance-scheduler
```

### 6. 安装 systemd 服务

```bash
sudo cp /opt/feiyang-maintenance-scheduler/deploy/feiyang-maintenance-scheduler.service \
        /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now feiyang-maintenance-scheduler
sudo systemctl status feiyang-maintenance-scheduler   # 应为 active (running)
```

### 7. 配置 Nginx 反向代理

```bash
# 把 example.com 全部替换为你自己的域名
sudo sed -i 's/example\.com/your-domain.com/g' \
    /opt/feiyang-maintenance-scheduler/deploy/nginx.conf

sudo cp /opt/feiyang-maintenance-scheduler/deploy/nginx.conf \
        /etc/nginx/sites-available/feiyang-maintenance-scheduler
sudo ln -sf /etc/nginx/sites-available/feiyang-maintenance-scheduler \
            /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t && sudo systemctl reload nginx
```

### 8. 申请 Let's Encrypt HTTPS 证书

```bash
sudo certbot --nginx -d your-domain.com
```

按提示输入邮箱、同意条款，跳转选项选 `2`（强制 HTTPS）。

### 9. 验证

浏览器访问 `https://your-domain.com`，看到排班界面即部署完成。

---

## 三、接入飞书工作台（一键启动）

### 1. 启用「网页应用」能力

[开发者后台](https://open.feishu.cn/app) → 选择本应用 → 左侧「**添加能力**」 → 找到 **网页** → 「启用」。

### 2. 填写首页地址

进入「**网页**」配置页：

| 字段 | 值 |
|---|---|
| PC 端首页 | `https://your-domain.com/` |
| 移动端首页 | `https://your-domain.com/` |
| 桌面端图标 | 120×120 png（俱乐部 logo 即可） |

### 3. 添加服务器 IP 到白名单（推荐）

左侧「**安全设置** → **IP 白名单**」添加服务器出口 IP：

```bash
# 在服务器上查询
curl ifconfig.me
```

### 4. 扩大可用范围

左侧「**权限管理**」→ 最下方「**应用可用范围**」→ 选「俱乐部全员」或具体部门。否则只有你本人能看到。

### 5. 发布新版本

左侧「**版本管理与发布**」→ 「创建版本」 → 填版本号 + 说明 → 「申请版本发布」 → 管理员审批通过。

### 6. 使用方式

- 飞书左下角「**工作台**」 → 搜索应用名 → 点击图标进入
- 或直接访问 `https://your-domain.com`（非飞书用户亦可用）

---

## 四、后续更新

在本地改完代码后 `git push`，到服务器上：

```bash
cd /opt/feiyang-maintenance-scheduler
sudo git pull
sudo ./.venv/bin/pip install -r requirements.txt   # 如依赖有变
sudo systemctl restart feiyang-maintenance-scheduler
```

---

## 五、日常运维

```bash
# 状态
sudo systemctl status feiyang-maintenance-scheduler

# 实时日志
sudo journalctl -u feiyang-maintenance-scheduler -f
sudo tail -f /var/log/feiyang-maintenance-scheduler/error.log

# 重启
sudo systemctl restart feiyang-maintenance-scheduler

# Nginx 重载（仅改 nginx.conf 时需要）
sudo nginx -t && sudo systemctl reload nginx
```

HTTPS 证书 certbot 会自动续期，无需手动干预。

---

## 六、安全补强（强烈建议至少做一项）

当前部署后**任何拿到 URL 的人都能操作**。生产环境至少选一种：

### A. Nginx 基础认证（5 分钟，最简单）

```bash
sudo apt install -y apache2-utils
sudo htpasswd -c /etc/nginx/.htpasswd admin   # 输入密码
```

在 `/etc/nginx/sites-available/feiyang-maintenance-scheduler` 的 `location / { ... }` 内追加：

```nginx
auth_basic "Feiyang Scheduler";
auth_basic_user_file /etc/nginx/.htpasswd;
```

`sudo systemctl reload nginx` 即可。访问时会弹账号密码对话框。

### B. 飞书免登录（规范、但需改代码）

使用 [飞书 JS-SDK](https://open.feishu.cn/document/uAjLw4CM/ukTMukTMukTM/web-app/overview)：前端拿到 `tt.requestAccess` 返回的 `code` → 后端用 `app_access_token` 换 `user_access_token` → 校验用户是否属于允许的部门（部长团 / 维修部等）。

如需该方案的改造补丁，在 issue 里告知即可。

---

## 七、故障排查

| 症状 | 可能原因 / 排查 |
|---|---|
| `systemctl status` 非 active | `journalctl -u feiyang-maintenance-scheduler -n 100` 看错误栈 |
| 浏览器 502 | gunicorn 未启动 or 端口非 5000；检查 `ss -lntp \| grep 5000` |
| HTTPS 证书申请失败 | 80 端口未放开 / 域名未解析到服务器 |
| 飞书 API `99991672` | 应用权限未发布或未审批通过 |
| 飞书 API `1254001` | IP 未加白名单（部分敏感接口要求） |
| 数据表读到但字段空 | 字段名或选项文本不匹配，用 Web UI 的「查看字段」排错 |

---

## 八、文件索引

| 路径 | 说明 |
|---|---|
| `deploy/feiyang-maintenance-scheduler.service` | systemd 服务单元 |
| `deploy/nginx.conf` | Nginx 站点配置（需替换域名） |
| `.env.example` | 凭证模板（拷贝为 `.env` 后填真实值） |
| `app.py` / `templates/index.html` | Flask Web 应用 + UI |
| `config.py` | 时段常量、字段名约定、阈值等 |
