# 昊云网络巡检助手(Haoyun Network Patrol)

面向网络工程师的**设备巡检小工具**:选几台设备一键巡检,产出**一份合并的整体巡检报告**(HTML / Word / Excel / PDF),支持 AI 大模型分析汇总——适合乙方工程师到甲方现场巡检后直接交付整体报告的场景。

- 双击即用:默认是 **Windows 桌面小工具**(原生界面,零依赖、无浏览器、无黑框);`--web` 参数可起网页模式远程访问(带登录认证)
- 桌面端纯 Tkinter 实现,不引入任何第三方 UI 依赖;按钮/主题为纯标准库自绘

## 两种版本,按需取用

| 版本 | 去哪拿 | 适合谁 |
|------|--------|--------|
| **发布版(正式交付)** | [Releases](../../releases)(GitHub)或 [Gitee 发行版](https://gitee.com/nmghywx/xjzs/releases) 下载绿色包 zip,解压双击「启动巡检助手.exe」即用 | 网络工程师 / 现场交付,无需任何开发环境 |
| **源码版** | Clone 本仓库,`pip install -e .` 后运行 | 开发者 / 二次开发(MIT 协议允许) |

> 版本号规则:Release 的 `vX.Y.Z` 即发布版本号,与 `pyproject.toml` 的 version、[CHANGELOG](CHANGELOG.md) 一一对应;main 分支为开发主线,可能包含尚未发布的改动。

## 平台支持

| 平台 | 推荐形态 | 说明 |
|------|----------|------|
| Windows 10/11 | **绿色包 exe**(见 [Releases](../../releases) / [Gitee 发行版](https://gitee.com/nmghywx/xjzs/releases),双击即用) | 主力交付形态,桌面小工具 + Web 全功能 |
| Linux / macOS | `pip install -e .` 后运行(见下方快速开始) | Web 模式全功能;桌面小工具可跑(需系统 Tk) |
| 信创 Linux(银河麒麟/统信 UOS) | **绿色包 tar.gz**(x86_64 / aarch64 飞腾·鲲鹏,见 [Releases](../../releases) / [Gitee 发行版](https://gitee.com/nmghywx/xjzs/releases)) | 解压即用,CLI 巡检 + Web 模式(无图形库自动转 Web) |
| 任意终端浏览器 | `--web` 模式远程访问 | 天然跨平台 |

> PDF 导出:Windows 自动使用 Microsoft Word;Linux/macOS 自动改用 LibreOffice(`sudo apt install libreoffice-writer fonts-wqy-microhei` 或 `brew install --cask libreoffice`)。

## 功能特性

- **7 家全国产厂商 10 种设备类型**:H3C×3(comware 交换机 / S7506E / SecPath 防火墙)、华为×2(VRP 交换机 / USG 防火墙)、锐捷、深信服、迪普、中兴 ZXR10、迈普 MyPower
- **三种采集通道**:SSH(netmiko,支持 super 密码自动提权)/ Web 控制台 / API
- **YAML 规则引擎**:检查项判定 PASS / FAIL / UNKNOWN,规则文件可自行增改,无法识别的回显如实标记 UNKNOWN 绝不误报"正常"
- **合并巡检报告**:一次任务多台设备 → 一份整体报告(汇总 / 风险项 / 逐台检查项 / 原始回显平铺展示,敏感信息自动脱敏)
- **多格式导出**:HTML(含结构化 JSON)、Word(商务正式版含封面与签字页)、Excel 台账、PDF
- **AI 分析**:内置 DeepSeek / 智谱 / 通义 / Kimi / 豆包 / 文心 / 星火 / 混元 / Ollama 等 OpenAI 兼容预设,结合设备原始回显做整体分析(健康评分 / 关键发现 / 处置建议),默认关闭,配 Key 即用
- **资产管理**:设备 / 客户(甲方)档案,Excel 台账智能导入,子网扫描发现设备
- **巡检历史**:SQLite 落库,支持多期对比、上期复查
- **登录认证**:Web 模式 PBKDF2-SHA256 口令散列、失败限速、改密即失效旧会话
- **定时巡检**:可安装 Windows 计划任务(每周 / 每月全量巡检)
- **绿色打包**:一条命令产出免安装绿色包,内置在线自动更新

## 快速开始

### 方式一:绿色包(推荐给现场使用)

从 [Releases](../../releases) 下载绿色包,解压后双击「启动巡检助手.exe」即可:

- 首次运行自动生成 `config\`(演示设备)与 `output\`(报告目录)
- 网页远程访问:命令行执行 `启动巡检助手.exe --web`,默认地址 `http://127.0.0.1:8765/ui`
- 默认网页登录账号 `admin / admin123`,登录后请到「系统设置 → 账号安全」修改;忘记密码删除 `config\auth.yaml` 重启即恢复默认

### 方式二:源码运行

```bash
git clone <本仓库地址>
cd 昊云网络巡检助手            # 或你克隆后的目录名
pip install -e .               # Python >= 3.10

python -m patrol.launcher          # 桌面小工具
python -m patrol.launcher --web    # 网页模式(自动开浏览器)
python -m patrol -c config/devices.yaml   # CLI 批量巡检
```

> PDF 导出依赖本机安装 Microsoft Word;HTML / Word / Excel 导出无此要求。

## 支持设备

| 厂商 | 设备类型 | 通道 |
|------|----------|------|
| H3C / 华三 | comware_switch · s7506e · secpath_firewall | SSH / Web |
| 华为 | vrp_switch · usg_firewall | SSH |
| 锐捷 | rgos_switch | SSH |
| 深信服 | ngaf_firewall | Web / API |
| 迪普 | dptech_firewall | API |
| 中兴 | zxr10_switch | SSH |
| 迈普 | mypower_switch | SSH |

> 新增厂商驱动按标准回显格式编写,中兴 / 迈普 / USG / SecPath 解析器建议先在自己的设备上试跑一次;遇到 UNKNOWN 请保留报告回传适配(报告内含完整原始回显)。

## 配置说明

| 文件 | 用途 |
|------|------|
| `config/devices.yaml` | 设备清单(演示样例,请替换) |
| `config/customers.yaml` | 客户(甲方)档案 |
| `config/rules/*.yaml` | 巡检规则,可按需增改 |
| `config/ai.yaml` | AI 分析配置(填 API Key 启用) |
| `config/auth.yaml` | Web 登录账号(首跑自动生成) |

## 运行测试

```bash
pip install -e ".[dev]"
python -m pytest -q          # 900+ 用例
```

## 打包绿色版

```bash
python packaging/build_portable.py
# 产物: dist/昊云网络巡检助手/ 与同名 zip
```

## 目录结构

```
src/patrol/
├── launcher.py     # 入口分发:无参=桌面,--web=网页,其余=CLI
├── collector/      # SSH / Web / API 采集
├── drivers/        # 7 厂商驱动与解析器(注册制)
├── analyzer/       # YAML 规则引擎
├── reporter/       # HTML / Word / Excel / PDF 报告
├── desktop/        # Tkinter 桌面小工具(六面板)
├── api/            # FastAPI 网页模式 + 登录认证
├── ai/             # 大模型分析(13 家预设)
├── storage/        # YAML 存储 + SQLite 巡检历史
└── utils/          # 文件名消毒 / 脱敏 / 原子写
```

## 开源协议

[MIT License](LICENSE) —— 允许二次开发、修改、分发与商业使用,保留版权声明即可。

作者:**昊云** · QQ:370428679

发现 bug 或想交流使用经验,欢迎提 [Issue](../../issues);现场遇到 UNKNOWN 判定,请附报告文件(内含原始回显)反馈,便于离线适配解析器。
