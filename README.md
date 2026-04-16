# feiyang-maintenance-scheduler

> 仓库：https://github.com/JerryThe-cat/feiyang-maintenance-scheduler

飞扬俱乐部大修活动自动化排班工具，基于飞书开放平台的企业自建应用：读取指定多维表格 → 按规则自动排班 → 回填结果。

## 项目结构

```
feiyang-maintenance-scheduler/
├── 需求说明.md                 # 原始需求文档
├── requirements.txt            # Python 依赖
├── .env / .env.example         # 飞书凭证（.env 不提交到仓库）
├── config.py                   # 常量 + 配置加载
├── feishu_client.py            # 飞书 API 客户端（鉴权 + Bitable 读写）
├── scheduler.py                # 排班核心算法（干事 / 技术员）
├── app.py                      # Flask Web 应用（一键排班界面）
├── main.py                     # CLI 入口（命令行直接排班）
├── templates/index.html        # Web UI
├── tests/test_scheduler.py     # 离线单元测试（无需飞书）
└── deploy/
    ├── DEPLOY.md                                # 生产环境部署手册
    ├── feiyang-maintenance-scheduler.service    # systemd 服务单元
    └── nginx.conf                               # Nginx 反向代理配置
```

## 一、本地开发 / 自用

```bash
git clone https://github.com/JerryThe-cat/feiyang-maintenance-scheduler.git
cd feiyang-maintenance-scheduler
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # 按需修改 App ID / Secret
python app.py          # 打开 http://127.0.0.1:5000
```

> ⚠️ **安全提醒**：`.env` 中的 `FEISHU_APP_SECRET` 为敏感凭证，已在 `.gitignore` 中过滤。如 Secret 泄露，请在飞书开发者后台重置。

## 二、飞书侧准备

1. **应用已开通权限**：多维表格读取 / 复制 / 创建 / 修改。
2. **应用加入协作**：在目标多维表格中，添加应用为协作者并授予编辑权限。
3. **字段名对齐**：默认按以下字段名读写，如不一致可在 Web UI 的"高级"面板或 `config.py` 中修改：

   **干事表**
   - 姓名、性别、部门、报名时间段（多选）
   - 安排时间段（脚本回填）
   - 安排位置（脚本回填）

   **技术员表**
   - 姓名、报名时间段（多选）
   - 安排时间段（脚本回填）

## 三、启动 Web 界面（推荐）

```bash
python app.py
# 浏览器打开 http://127.0.0.1:5000
```

操作步骤：

1. 粘贴多维表格 URL（形如 `https://xxx.feishu.cn/base/<app_token>?table=<table_id>`）
2. 点击**加载数据表** → 从下拉列表中选择
3. 选择**排班类型**（干事 / 技术员）
4. 可勾选"仅预览"先验证结果再写回
5. 点击**执行排班**，结果会以 JSON 形式展示，并写回到表格

## 四、使用 CLI（便于脚本化）

```bash
# 干事排班 + 真实写回
python main.py staff --url "https://xxx.feishu.cn/base/<app_token>?table=<table_id>"

# 技术员排班 + 仅预览
python main.py technician --url "..." --dry-run
```

## 五、排班规则（与需求一致）

### 干事

- 5 个正式时段 + 1 个"暂定"（暂定不参与排班）
- 每人从报名时段中唯一分到一个时段
- 每时段点位：**1 号位 / 4 号位 / 5 号位 / 6 号位 / 机动位(≤2) / 学习位(无上限)**
- **1 号位 / 4 号位优先**"部门"含**维修部**的干事；若无维修部则由其他部门顶替
- **首/末时段**优先**男性**；**尽力**保证每时段 ≥ 6 人
- 首/末时段取当次活动**实际启用**的首尾（非固定）
- 若"安排时间段 / 安排位置"已有值则**跳过**，不覆盖

### 技术员

- 4 个时段，不涉及点位
- 按报名时段进行人数均衡分配
- 已有"安排时间段"值的记录跳过

## 六、离线自测

```bash
python -m tests.test_scheduler
```

该脚本构造虚拟报名数据，调用 `scheduler.py` 校验规则，无需连接飞书。

## 七、常见问题

- **`app_token` 解析失败**：请确保 URL 形如 `.../base/<app_token>?table=<table_id>`。
- **飞书返回 99991663 / 99991672**：说明 App ID/Secret 错误或 IP 白名单未配置。
- **没有修改权限**：需在飞书多维表格中把应用加为协作者并授予"可编辑"。

## 八、部署到云服务器 + 接入飞书工作台

生产环境部署、HTTPS 证书申请、飞书「网页应用」配置详见 **[deploy/DEPLOY.md](deploy/DEPLOY.md)**。一句话流程：

```
克隆仓库 → venv 安装依赖 → 配置 .env → systemd 启动 gunicorn →
nginx 反向代理 + certbot HTTPS → 飞书开发者后台填首页 URL → 发布
```

## 九、待确认项（开发期可再对齐）

见 `需求说明.md` 第五节：
- 字段名与实际表格是否完全一致（Web UI 支持手动指定）
- 1/4 号位无维修部时是否由其他部门顶替（当前为**顶替**）
- 末时段 ≥6 人的硬/软性：当前为**尽力而为**
- 重复排班：当前为**跳过**
- 飞书侧触发方式：当前 Web UI 即可；如需接入飞书卡片 / 机器人 / 工作流，在 `app.py` 基础上增加对应路由即可。
