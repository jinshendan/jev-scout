# 调查取消操作的调用路径

[English](demo.md) · [简体中文](demo.zh-CN.md)

本教程使用虚构的 C++ 源码树 `examples/cancellation`，展示 Jev Scout 0.4.0 的能力：只读搜索仓库、记录源码证据、可选的相邻读取、显式恢复和冻结输入下的策略比较。教程不会编译示例、执行回调、复现缺陷、确定根因，也不会提出已经验证的修复。

## 运行调查

按照[项目 README](../README.zh-CN.md)中的说明安装 Jev Scout 后，在仓库根目录运行：

```sh
scout investigate \
  --repo examples/cancellation \
  --task 'Investigate whether Request::cancel removes queued callbacks.' \
  --output .scout/demo \
  --max-steps 6 \
  --max-context-chars 1200
```

这里的任务明确指出了一个具体符号。基于规则的调查器可以利用该名称及相关文本定位源码候选。第一个里程碑的规则基线不需要 Jev API Key。命令中的英文任务文本与英文教程保持一致，以得到相同的检索输入。

查看 `.scout/demo` 中生成的三个文件：

- `report.md`：便于阅读的调查报告。
- `evidence.json`：记录下来的源码证据。
- `events.jsonl`：调查事件日志。

在记录的行号处打开每个引用的源码文件，并检查周围代码。文件匹配是调查线索，不是计算得到的 C++ 调用图。

如需进一步扩大调查范围，可以使用 `examples/cancellation/task.txt` 中的准确符号名：`Request::queue_completion`、`Queue::enqueue`、`Queue::remove_for` 和 `Queue::dispatch_one`。一次简短的初始搜索未必覆盖所有相关路径。如果缺少某个关联，应扩展问题或检查相邻定义。

使用 `--max-steps N` 和 `--max-context-chars N` 限制调查范围。预算限制可能使证据采集在检查完所有有用源码之前停止；不能据此认定未找到的路径不存在。

每条命令都应使用位于 `examples/cancellation` 之外的新输出目录。如果先前运行已经生成了 `.scout/demo`，请换一个目录名，并在下面的恢复命令中使用同一个新名称。

## 检查相邻源码

开启相邻证据扩展，运行一次新的调查：

```sh
scout investigate \
  --repo examples/cancellation \
  --task 'Investigate whether Request::cancel removes queued callbacks.' \
  --output .scout/followup-demo \
  --max-steps 12 \
  --max-context-chars 1200 \
  --max-followups 6
```

本次运行中，运行时最多可以提供六个新候选，每个都是成功读取过的文件中紧邻原窗口、最多九行的片段。下一步动作仍由规则策略选择，所有被选中的读取共用十二步预算。默认的 `--max-followups 0` 保留原有固定候选集合。

对照 `.scout/followup-demo/evidence.json` 中的 `initial_candidate_ids`、`generated_candidate_lineage` 和 `expansion`。每个新增候选都关联允许生成它的候选与观察记录。`candidate_generated` 事件保留完整候选和父记录 ID；`frontier_expansion_checked` 事件记录扩展数量与生成的 ID。所提供候选可能最终未被选中，但仍然消耗配额。

相邻窗口不会搜索新文件，也不能证明完整覆盖。长行可能超过 4,000 字符的片段限制。若仍缺少证据，可扩大英文任务的范围，或手动检查源码。确切限制与父子关系见[相邻扩展指南（英文）](follow-up-evidence.md)。

## 恢复一条已保留的观察

在生成的 `evidence.json` 中找到观察 ID，然后显式请求恢复。第一条观察的 ID 通常是 `o0001`：

```sh
scout recover \
  --evidence .scout/demo/evidence.json \
  --repo examples/cancellation \
  --observation o0001 \
  --output .scout/recovery \
  --max-context-chars 1200
```

查看 `.scout/recovery/report.md` 和 `recovery.json`。恢复会保留所请求的原始摘录，并先核对当前源码，再将匹配的内容放入有界上下文。它能够恢复被移出上下文的记录，但不会继续原来的运行。重复使用 `--observation` 可以请求其他 ID。[证据恢复指南（英文）](evidence-recovery.md)说明了如何处理过期和不匹配的记录。

## 使用同一份捕获输入进行比较

运行离线一致性检查：

```sh
scout compare \
  --repo examples/cancellation \
  --task 'Investigate whether Request::cancel removes queued callbacks.' \
  --output .scout/comparison \
  --max-steps 6 \
  --max-context-chars 1200
```

默认挑战者是另一个新建的规则策略。两组都使用一次捕获的初始候选集合和源码内容。查看 `comparison.json`、顶层的 `report.md`，以及 `rule/` 和 `challenger/` 下的标准证据包。冻结观察描述的是已捕获的内容；单独的工作区检查会说明运行结束后原始文件是否仍然匹配。

两组规则决策一致，只能作为一致性检查，不能视为质量或成本结论。`--challenger jev` 会显式启用向 TypeSafe 传输源码，并要求设置环境变量中的密钥。在私有源码上运行前，请阅读[策略比较指南（英文）](policy-comparison.md)。本 demo 尚未证明真实 Jev 调用的收益。

若要在两个离线比较分支中使用同样的相邻扩展设置：

```sh
scout compare \
  --repo examples/cancellation \
  --task 'Investigate whether Request::cancel removes queued callbacks.' \
  --output .scout/followup-comparison \
  --max-steps 12 \
  --max-context-chars 1200 \
  --max-followups 6
```

两组共享初始候选和捕获的源码，后续菜单根据各自成功的读取生成。比较 schema 2 保留各分支内的候选 ID，但按源码与动作身份衡量一致性。请将各分支的 `expansion` 记录与一致性数值一起检查。

## 阅读证据

源码提供了以下人工检查目标。实际报告的排序和所包含的摘录，取决于调查器及其限制。

| 目标 | 检查内容 | 仅凭源码无法确定的事项 |
| --- | --- | --- |
| `request.cpp`：`Request::cancel` | 对 `cancelled_` 的写入；该函数体是否调用队列移除方法 | 预期的取消操作契约 |
| `request.cpp`：`Request::queue_completion` | 存储的闭包中的 `weak_request`、`lock()` 和取消状态检查 | 真实应用的生命周期与同步规则 |
| `queue.cpp`：`Queue::enqueue` | 保存到 `callbacks_` 中的条目 | 哪些应用路径将任务加入队列 |
| `queue.cpp`：`Queue::remove_for` | 按所有者移除条目的操作 | 是否所有调用者都正确使用了它 |
| `queue.cpp`：`Queue::dispatch_one` | 在 `entry.callback()` 之前弹出条目的操作 | 运行时调度或并发交错 |
| `call_site.cpp` | 先入队、再取消的源码场景 | 已复现的失败或已执行的断言 |

需要分开考虑两个问题：取消时是否移除了队列条目，以及取消后是否还能运行该条目的 `on_complete` 回调。派发时的条件检查可以影响第二个问题，即使取消时没有移除条目。调查应保留每条观察背后的源码引用，并明确列出尚未解决的问题。

Scout 的第一个里程碑记录文本证据。它不能证明某个符号解析到哪个重载、某条源码路径确实被执行、某个回调存在释放后使用问题，或取消操作具有线程安全性。这个虚构示例采用单线程设计，没有声称存在内存安全缺陷。

## 第一个里程碑之后的计划验证

未来的调查能力可能增加由编译器支持的符号索引，并基于真实的 `compile_commands.json` 使用 clangd 交叉引用。在得出行为结论之前，项目需要提供构建目标、断言所选取消操作契约的测试，以及覆盖回调所有权和请求销毁的已执行场景。之后可以使用 AddressSanitizer 和 UndefinedBehaviorSanitizer 辅助检查这些场景；只有在并发设计及其测试已经存在时，ThreadSanitizer 才相关。

这些能力和检查都属于后续工作。本教程没有报告编译结果、sanitizer 结果、缺陷复现或编码基准成绩。组件边界与后续计划见[架构说明](architecture.zh-CN.md)和[路线图](roadmap.zh-CN.md)。
