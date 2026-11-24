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
| Linux / macOS | `pip install -e .` 后运行(见下方快速开始) | Web 模式全功能;桌面小工具需系统 Tk |
| 信创 Linux(银河麒麟/统信 UOS) | **绿色包 tar.gz**(x86_64 / aarch64 飞腾·鲲鹏,见 [Releases](../../releases) / [Gitee 发行版](https://gitee.com/nmghywx/xjzs/releases)) | 解压即用,CLI 巡检 + Web 模式(包内不含图形库,运行即 Web 模式) |
| 任意终端浏览器 | `--web` 模式远程访问 | 天然跨平台 |

> - PDF 导出:Windows 自动使用 Microsoft Word;Linux/macOS 自动改用 LibreOffice(`sudo apt install libreoffice-writer fonts-wqy-microhei` 或 `brew install --cask libreoffice`)。
> - 验证口径:每个发布包在发布前都跑成品冒烟——连上模拟设备,命令行巡检与网页端巡检各跑一遍(登录 → 采集 → 判定 → 出报告);Windows 包另做桌面窗口冒烟与人工走查,Linux 包在同代 glibc(glibc 2.28,与银河麒麟 V10 / 统信 UOS 同代)的干净容器里跑。**信创实机、以及 Linux 下的真实设备采集,都还没有验证过**;v0.2.0 的 Linux 包有缺陷,请使用 v0.2.1 及以上版本。

## 功能特性

- **7 家全国产厂商 10 种设备类型**:H3C×3(comware 交换机 / S7506E / SecPath 防火墙)、华为×2(VRP 交换机 / USG 防火墙)、锐捷、深信服、迪普、中兴 ZXR10、迈普 MyPower
- **多种采集通道**:SSH / Telnet / Console 串口(netmiko,支持 super 密码与 enable 密码自动提权)、Web 控制台、API、SNMP v2c
- **YAML 规则引擎**:检查项判定 PASS / FAIL / UNKNOWN,`config/rules/` 下的规则文件启动时自动合并加载;回显为空、命令不被设备支持或格式无法识别时如实记为 UNKNOWN,不会算作"正常"
- **合并巡检报告**:一次任务多台设备 → 一份整体报告(汇总 / 风险项 / 逐台检查项 / 原始回显平铺展示,敏感信息自动脱敏)
- **多格式导出**:HTML(含结构化 JSON)、Word(商务正式版含封面与签字页)、Excel 台账、PDF
- **AI 分析**:内置 DeepSeek / 智谱 / 通义 / Kimi / 豆包 / 文心 / 星火 / 混元 / Ollama 等 OpenAI 兼容预设,结合设备原始回显做整体分析(健康评分 / 关键发现 / 处置建议);未配置 Key 时不启用
- **资产管理**:设备 / 客户(甲方)档案,Excel 台账智能导入,子网扫描发现设备
- **巡检历史**:SQLite 落库,支持多期对比、上期复查、趋势与超阈值预测
- **结果如实呈现**:设备连不上时任务标为"失败"并可点开看每台原因;没有任何可判定的检查项时不给健康分
- **登录认证**:Web 模式 PBKDF2-SHA256 口令散列、失败限速、改密即失效旧会话
- **定时巡检**:可安装 Windows 计划任务(每周 / 每月全量巡检),命令行 `run` 与界面共用同一份设备档案
- **绿色打包**:一条命令产出免安装绿色包,内置在线自动更新(更新包须带 sha256 校验值)

## 快速开始

### 方式一:绿色包(推荐给现场使用)

从 [Releases](../../releases) 下载绿色包,解压后双击「启动巡检助手.exe」即可:

- 首次运行把 `config\devices.yaml` 里的演示设备导入设备库(`data\patrol.db`),并自动生成 `output\`(报告目录);之后设备在界面里维护,再改这个 yaml 不生效
- 网页远程访问:命令行执行 `启动巡检助手.exe --web`,默认地址 `http://127.0.0.1:8765/ui`
- 默认网页登录账号 `admin / admin123`,登录后请到「系统设置 → 账号安全」修改;忘记密码删除 `config\auth.yaml` 重启即恢复默认

### 方式二:源码运行

```bash
git clone <本仓库地址>
cd 昊云网络巡检助手            # 或你克隆后的目录名
pip install -e .               # Python >= 3.10

python -m patrol.launcher          # 桌面小工具
python -m patrol.launcher --web    # 网页模式(自动开浏览器)
python -m patrol                  # CLI 批量巡检:界面里启用的全部设备(退出码 0 正常 / 2 有异常项 / 3 全部设备未采集到)
```

> PDF 导出需要本机装有 Microsoft Word 或 LibreOffice 之一;HTML / Word / Excel 导出无此要求。

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

> 新增厂商驱动按标准回显格式编写。**中兴 / 迈普 / USG / SecPath 的解析器,以及 Telnet / 串口通道、等保基线规则,尚未在真机上逐项验证**,建议先在自己的设备上试跑;遇到 UNKNOWN 请保留报告回传适配(报告内含完整原始回显)。

## 配置说明

| 文件 | 用途 |
|------|------|
| `config/devices.yaml` | 首次启动导入的初始设备清单(演示样例);之后设备在界面维护,改动此文件不再生效 |
| `config/customers.yaml` | 客户(甲方)档案(首次启动导入) |
| `config/rules/*.yaml` | 巡检规则,启动时自动合并加载;`baseline_dengbao.yaml`(等保基线)默认关闭(`enabled: false`),真机验证后打开 |
| `config/ai.yaml` | AI 分析配置(填 API Key 启用) |
| `config/auth.yaml` | Web 登录账号(首跑自动生成,每个安装各自生成会话密钥) |
| `data/patrol.db` | 设备 / 客户 / 任务 / 审计(Windows 下设备密码用系统级加密保存) |

## 已知限制

- **问题处置没有闭环**:报告里发现问题后,没有"确认 → 整改 → 销号"的台账;确认单只是可打印页;设备白名单只能在数据里配置,界面上没有入口。
- **任务不能中途取消**,也没有任务级超时;退出程序时,正在采集的设备会跑完当前这一台。
- **审计不完整**:只有 REST 接口的写操作进了审计,界面上的增删改没有记录。
- 新增厂商与等保基线规则未经真机验证(见上)。
- Linux / macOS 下设备密码以明文保存在本地数据库(Windows 使用系统级加密)。
- 桌面小工具只在 Windows 上完整验证;自动更新没有签名校验与自动回滚。

## 运行测试

```bash
pip install -e ".[dev]"
python -m pytest -q          # 1000+ 用例(Windows 全量;其他平台不含桌面用例)
ruff check src tests scripts packaging   # 静态检查:语法错误与未定义名
```

## 打包绿色版

```bash
python packaging/build_portable.py                      # Windows 绿色包
python packaging/build_portable_linux.py --arch x86_64  # Linux 绿色包(需在 glibc 2.28 基线环境中构建)
# 产物: dist/ 下的程序目录与 zip / tar.gz(不包含本机的登录凭据与发信配置)
# 打包后建议跑一遍成品冒烟:模拟设备 → 命令行巡检 + 网页端巡检,确认这个包真的能用
python scripts/smoke_portable_e2e.py
```

## 目录结构

```
src/patrol/
├── launcher.py     # 入口分发:无参=桌面,--web=网页,run 等=CLI
├── collector/      # SSH / Telnet / 串口 / Web / API / SNMP 采集
├── drivers/        # 7 厂商驱动与解析器(注册制)
├── analyzer/       # YAML 规则引擎
├── reporter/       # HTML / Word / Excel / PDF 报告
├── desktop/        # Tkinter 桌面小工具(六面板)
├── api/            # FastAPI 网页模式 + 登录认证
├── ai/             # 大模型分析(国内厂商预设)
├── storage/        # SQLite 统一仓库(设备 / 客户 / 任务 / 审计)与巡检历史
└── utils/          # 文件名消毒 / 脱敏 / 原子写 / 配置快照
```

## 开源协议

[MIT License](LICENSE) —— 允许二次开发、修改、分发与商业使用,保留版权声明即可。

作者:**昊云** · QQ:370428679

发现 bug 或想交流使用经验,欢迎提 [Issue](../../issues);现场遇到 UNKNOWN 判定,请附报告文件(内含原始回显)反馈,便于离线适配解析器。
