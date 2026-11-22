# otel-span-attribute-consistency-validator
验证 span 属性类型、单位、基数和版本一致性

一个 Python 3.8+ 的 OpenTelemetry 属性一致性校验器。服务发布后，同一语义的
span 属性可能在不同服务间出现秒/毫秒混用、字符串/整数错误码、新旧字段混淆等
问题——轨迹仍能采集，但统计和告警已经失真。本工具对服务 schema 与样本数据做
离线一致性检查，并生成迁移计划。

## 范围说明

**本工具只分析离线的 schema 和样本数据（JSON 文件），不连接 Collector、
OTLP 端点或任何在线遥测后端。** 样本需要由你自行导出后传入。

## 输入

单个 JSON 文档，包含三个顶层键：

- `semconv_version`：全局语义约定版本。
- `services`：每个服务的 schema——属性名、`type`（string/int/double/boolean/
  map/数组）、`unit`、`enum`、`required`、`semconv_version`、`deprecated`、
  `renamed_to`，以及 `dual_write` 规则（`old`/`new`/`read_priority`/
  `retire_after`）和 `dynamic_keys` 基数策略（`max_keys`、
  `max_values_per_key`）。
- `spans`：样本 span，含 `attributes`、`resource`、`events`、`links`。

## 检查项

- 跨服务类型冲突（如状态码 string vs int）；样本值类型不匹配时**只报告，
  绝不静默强转**（`"200"` 不会被当成 `200` 通过检查）。
- 单位不一致（s/ms/us/ns），给出显式换算系数；单位缺失或无已知换算时标记为
  无法安全判断。
- 属性重命名与新旧字段混淆；迁移期间允许显式双字段，但 `dual_write` 规则必须
  声明读取优先级和退役窗口，双字段取值冲突会被标记。
- 非法枚举值、缺失必填属性、语义版本不一致。
- 动态 map 与前缀动态键的基数（键数、每键取值数）超限告警；未声明基数策略的
  map 标记为无法安全判断。

## 输出

JSON 报告，包含：

- `inconsistencies`：不一致项（code/severity/attribute/services/details）。
- `affected_services`：受影响服务列表。
- `compatibility`：建议的兼容级别（`full` / `backward` / `forward` / `none`，
  取所有问题中最弱的一级）。
- `migration_phases`：迁移阶段——`dual-write`（双写/单位换算）、
  `consumer-switch`（消费方切换读取优先级）、`retire`（退役窗口后删除旧字段）。
- `undecidable`：仍无法安全判断的数据（未声明属性、缺单位、无策略的 map、
  无 schema 的服务）。

## 使用

```bash
python -m otel_attr_validator input.json   # 有 error 级问题时退出码为 1
```

或在代码中调用：

```python
from otel_attr_validator import (
    ConsistencyValidator, MigrationPlanner, ValidationInput, ValidationReport,
)

data = ValidationInput.from_dict(document)
findings = ConsistencyValidator().validate(data)
phases = MigrationPlanner().plan(data, findings)
report = ValidationReport.build(findings, phases).to_dict()
```

校验是确定性且幂等的：同一输入重复执行产生完全一致的报告。

## 测试

```bash
python -m unittest discover -s tests
```

覆盖秒/毫秒混用、字符串/整数状态码、重命名字段与双写规则、动态 map、
高基数标签和重复执行幂等性。
