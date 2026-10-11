# Advanced Comfort Controller · 高级温湿度控制器

[![Tests](https://github.com/aemediatodd/advanced-comfort-controller/actions/workflows/tests.yml/badge.svg)](https://github.com/aemediatodd/advanced-comfort-controller/actions/workflows/tests.yml)

把独立温湿度传感器、空调、风扇、开关、加湿器和除湿机组合成一个可配置节点的 Home Assistant 控制器。

**初始版本 0.1.0：支持 HACS 自定义仓库安装。需要 Home Assistant 2026.2.3 或更新版本。尚未验证真实家电。**

## 功能

- 创建标准 `climate` 温控器或 `humidifier` 恒湿器实体，可创建多个控制器。
- 独立主传感器、主设备、任意多个副设备；可另绑一个温度/湿度传感器。
- 不限定节点数量；按 **测量值 − 目标值** 设置每个节点的上下限、优先级和适用模式。
- 每个节点使用 Home Assistant 原生动作编辑器：空调设温、模式、风速，风扇百分比/预设模式，开关，加湿除湿动作，`select` / `number` / 脚本和其他 HA 动作均可组合。
- 动作可以写 `{{ target - 2 }}` 等模板，目标变化后自动重新计算。
- 中文/英文配置流程；节点增删改、批量 YAML 导入，无需编辑 `configuration.yaml`。
- 回差、动作切换最短间隔、主传感器上报超时、动作错误诊断、可取消的脚本执行。

## 安装

### HACS 自定义仓库

HACS → 右上角菜单 → 自定义仓库，添加：

```text
https://github.com/aemediatodd/advanced-comfort-controller
```

类别选择 **Integration / 集成**，下载后重启 Home Assistant。随后在 **设置 → 设备与服务 → 添加集成** 搜索 **Advanced Comfort Controller**。

[一键打开 HACS 仓库](https://my.home-assistant.io/redirect/hacs_repository/?owner=aemediatodd&repository=advanced-comfort-controller&category=integration)

本项目是 HACS 自定义仓库，未提交 HACS 默认商店。

### 手动安装

把 `custom_components/advanced_comfort` 文件夹复制到 Home Assistant 的 `config/custom_components/`，重启后添加集成。

## 配置流程

1. 输入名称，选择温控器或恒湿器。
2. 绑定主传感器、主设备和副设备。温控器主传感器为温度，恒湿器主传感器为相对湿度；副传感器是另一种测量值。
3. 设置目标范围、回差、动作切换间隔、传感器上报超时。
4. 添加节点，设置温差/湿差上下限和动作。也可从 [六节点温控示例](examples/temperature-six-nodes.yaml) 或 [恒湿示例](examples/humidity-nodes.yaml) 复制整个列表到“批量导入节点”。导入会追加节点；每次会生成新 ID。
5. 检查停机动作，覆盖所有受控设备。首次绑定常见开关类实体时会自动生成关闭动作；修改绑定后需要同步更新这些动作。
6. 保存，从实体卡片手动开启控制器。

后续编辑：**设置 → 设备与服务 → 该集成 → 配置**。保存会重新加载控制器并执行停机动作；目标值会恢复，运行开关默认关闭。HA 重启同样默认关闭，需手动或由你自己的启动自动化重新开启。

## 规则语义

设 `delta = 测量值 − 目标值`。例如目标 26°C、实际 27.2°C，`delta = 1.2`。

- 每个节点范围为 **[下限，上限)**：包含下限，不包含上限；留空为无界。
- 数字越大的优先级越先检查。没有回差保持时，重叠范围只执行第一个匹配节点；同优先级按保存的列表顺序，编辑同优先级节点会把它排到该组末尾。
- 有回差时，当前节点会保持到温差离开扩展后的范围。例如 `[1, +∞)`、回差 0.1，会保持到温差 `< 0.9`；即使别的高优先级节点也匹配，当前节点仍优先保持。需要严格优先级可把回差设为 0。
- 最短切换间隔适用于进入节点、节点切换、目标值或模式改变后的动作重发。等待期间保留上次设备状态，10 秒计时器会继续检查；关闭/主传感器故障/无节点匹配会立即走停机动作，重新开启仍遵守间隔。默认 120 秒；不是设备反馈驱动的压缩机保护器。
- **未匹配节点执行停机动作**，不会无限保持旧的制冷/制热输出。
- 同一节点不会在每次传感器更新时重复发命令；目标值或控制模式改变会重发。手动改动底层设备不会立即被覆盖；本版没有保活重发功能。
- 节点动作按顺序执行；新节点、关闭和主传感器故障会取消旧脚本。已经发出的设备指令无法撤回，因此每个节点应完整定义各设备的期望状态。
- 模式留空适用于所有开启模式。温控器支持 `auto/cool/heat`；恒湿器支持 `auto/humidify/dehumidify`。**模式是规则筛选条件**：例如只允许自动模式反向制热，请将该制热节点模式限定为 `auto`。
- `activity` 只用于温控器显示“制冷/制热/送风”等，不会替代节点动作，也不是设备运行反馈。
- 湿度偏移使用**百分点**，例如目标 50%、偏移 +10 表示 60% RH。

## 你提出的六节点场景

原始描述有未覆盖区间（如目标值到目标 +0.5、目标 −1 到目标 −0.5）及“低于 −1/−2/−5”的重叠。示例将其整理成连续、互斥区间，作为可编辑起点：

| 节点 | 温差范围 | 主空调 | 副设备 |
|---|---|---|---|
| 强冷 | `≥ +1` | 制冷、目标 −2、最大风速 | 大风扇强劲/100%，小风扇直吹/100%，电暖器关 |
| 普通冷 | `[+0.5, +1)` | 制冷、目标 −2、自动风速 | 两风扇自动模式，电暖器关 |
| 轻冷 | `[−1, +0.5)` | 制冷、目标 −1、自动风速 | 两风扇 25%，电暖器关 |
| 睡眠 | `[−2, −1)` | 制冷、目标值、自动风速 | 大风扇睡眠，小风扇关，电暖器关 |
| 送风 | `[−5, −2)` | 送风 | 风扇和电暖器关 |
| 过冷保护 | `< −5` | 制热、目标值 | 两风扇关，电暖器最低挡 |

示例采用下限包含约定，恰好 −5 属于送风；恰好 −2 属于睡眠。这些边界和补齐区间都可以在界面中修改。若要逐字采用原始的不连续区间，可删除补齐范围，空隙会执行停机动作。

示例绑定约定：`primary` 为空调；`auxiliaries[0]` 为大风扇、`[1]` 为小风扇、`[2]` 为 `climate` 电暖器。索引顺序会影响模板，修改绑定时应同步检查节点。也可以直接在动作中选具体实体，避免索引。

**风速/模式名称取决于设备。** `high/auto/boost/direct/sleep/low` 是示例字符串，请按设备实际暴露的 `fan_modes`、`preset_modes`、`hvac_modes` 替换。普通开关只能开关，不能凭空提供最低挡；若挡位由 `select` 或 `number` 实体提供，就在动作中调用该实体。

## 动作模板变量

| 变量 | 含义 |
|---|---|
| `target` | 当前控制目标；温度为 HA 系统单位，湿度为 % RH |
| `current` / `delta` | 当前主传感器值 / 当前值减目标值 |
| `primary` | 主设备实体 ID |
| `auxiliaries` | 副设备实体 ID 列表，按绑定顺序 |
| `temperature` / `humidity` | 已绑定传感器读数，缺失/失效时为 `None` |
| `controller_mode` | 当前控制模式 |

例如节点中的空调设温动作：

```yaml
- action: climate.set_temperature
  target:
    entity_id: "{{ primary }}"
  data:
    temperature: "{{ target - 2 }}"
```

温度传感器需要 `°C`、`°F` 或 `K` 单位，会转换到 HA 系统温度单位。湿度读数必须在 0–100。副传感器可在 `choose` / 条件动作中使用，但本版节点选择轴只看主传感器；副传感器失效不会触发整体停机，请在依赖它的模板中处理 `None`。设备目标值需在真实设备支持的范围内，集成不会自动替设备钳位。

## 停机与诊断

关闭、主传感器 `unknown/unavailable`、无效数字、超时、未命中节点和卸载时均执行停机动作。超时根据传感器的 **最近上报时间**，不是最近数值变化时间；以 10 秒间隔检查。副设备离线导致的动作异常会记录错误并尝试停机；30 秒或配置切换间隔（取较大值）后重试。

实体属性包含 `controller_status`、`active_node`、`delta`、`actions_applied`、`last_error`。`actions_applied` 表示脚本完成，不保证物理设备已响应。`continue_on_error` 的动作失败只写入 HA 日志，不会中断脚本。

每个物理设备建议由一个控制器负责；不要同时用温控器、恒湿器及其他自动化争抢同一个空调。主副设备绑定提供模板变量和初始停机动作，节点动作本身决定最终调用哪些设备。

## 现有项目对比

查阅日期：2026-10-11。没有找到完整覆盖此规则编辑方式的现成项目；这是文档调研结论，并非穷尽所有仓库。

| 项目 | 已有能力 | 与本项目需求的差别 |
|---|---|---|
| [Versatile Thermostat](https://github.com/jmcollin78/versatile_thermostat) | 独立温度计、开关/climate 控制、调节算法 | 没有在所查文档中找到任意多设备动作的节点编辑器及同类恒湿器 |
| [Auto Fan plugin](https://github.com/jmcollin78/vtherm_auto_fan_extended) | 按可调温差阈值选择主空调风速 | 最接近温差节点，但动作面向底层 climate 的风速 |
| [Dual Smart Thermostat](https://github.com/swingerman/ha-dual-smart-thermostat) | 冷热切换、辅助加热、风扇、除湿 | 设备角色及算法较固定，不是每节点任意动作 |
| [Better Thermostat](https://github.com/KartoffelToby/better_thermostat) | 外部传感器、TRV 校准及调节算法 | 更偏向温控阀与恒温算法 |
| [Smart Thermostat PID](https://github.com/ScratMan/HASmartThermostat) | PID/PWM 控制开关或阀门 | 不采用任意多节点动作模型 |
| [Template Climate](https://github.com/jcwillox/hass-template-climate) | 虚拟 climate 与自定义服务动作 | 可配合额外自动化实现，但要自己写温差规则和恒湿控制 |

## Development

Linux + Python 3.13:

```sh
python -m venv .venv
. .venv/bin/activate
pip install -r requirements-test.txt
ruff check .
pytest -q
```

Tests use real Home Assistant 2026.2.3 config flows, entity services and script execution. Home Assistant's test harness requires Linux; Windows can run the pure rule engine tests with plugin auto-loading disabled. CI is the authoritative full integration test environment. No actual household devices are accessed by these tests.

## English overview

An MIT-licensed Home Assistant custom integration that creates a thermostat (`climate`) or a hygrostat (`humidifier`) from an external sensor and arbitrary HA actions. Configure unlimited delta bands, priorities, mode filters, hysteresis, minimum action intervals, and fail-safe actions through config/options flows. Use native action selectors for device services and Jinja templates such as `{{ target - 2 }}`. Examples can be imported as node lists. On startup/reload the controller is off; enable it after reviewing its configuration. The secondary sensor is exposed to action templates, while band selection uses the primary sensor. Hardware validation is still required.
