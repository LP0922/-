# 2026-08-26 增量迁移

以原项目为功能与参数基准，同时更新 server 与 powder_sampling_control 两份 Python 项目。原目录不修改；目标目录独有数据不批量清理。

## 本次内容

- 专属粉末控制配置、统一产品约束、控制配置生成器和实验说明。
- 预测停机、尾段脉冲、堵料恢复、运动重试等当前源版本实现；不另行调参。
- 最新粉末指纹、粉末库、控制配置、实验日志、配置和测试。
- Vue 加粉页面：粉末必选、100–1000 mg 整数目标、自动配置预览、配置验证状态和告警、可选手动起始参数。
- 批量队列携带粉末身份，禁止混合粉末/任务类型，支持加粉批量停止和结果显示。
- 网格预览逐行修改/移除，按显式 sets 提交，修改输入列表后需重新展开。
- 粉末管理显示专属控制配置，并修正探针/搜索运行状态、搜索参数名和实验记录字段映射。

## 启动

在 server 目录运行：`py -3 scripts/device_control_server.py`。

在 web 目录运行：`npm run dev`，打开终端显示的地址（默认 http://localhost:5173）。

当前源版本默认天平 COM9、执行器 COM8；API 端口 8765。只能运行一个连接硬件的后端，不应与原目录后端同时启动。迁移不停止或重启已有服务。

## 回归验证

- 在 server 目录：`py -3 -B -m pytest -q -p no:cacheprovider`。
- 在 web 目录：`node --test tests/migration.test.js`、`npm run build`。
- `server/tests/migration_preview.py` 仅用于离线页面验证：不创建 DeviceReader，不打开串口，拒绝所有 POST。它不是设备控制服务。

## 回退

被覆盖的目标文件及两份已更名的旧指纹，保存在目标 `_migration_backups/20260826-时间/` 中；同目录的 migration-manifest.json 记录本次新增和覆盖项。目标独有文件保留。旧指纹已更名为 bentonite 与 water_loss_agent_2，旧 ID 移入备份，避免重新出现在粉末列表。

注意：源配置中的 draft / provisional 等状态原样保留；迁移与离线测试不等于真实设备工艺验收。
