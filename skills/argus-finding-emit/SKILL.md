# argus-finding-emit

将 detector 的结构化观察转换为符合 `Finding` 契约的审计结果。

## 调用条件

仅当 detector 已提供可定位事实（rule、path、line、source_sha256、脱敏 evidence）时调用。

## 禁止条件

- 不得根据模型猜测创建 finding；
- 不得写最终 release gate；
- 不得包含原始 secret、私有推理、绝对路径或 `..`；
- critical/high 缺少 file+line+evidence 时拒绝。

## 失败语义

输入非法返回 `invalid_input`；路径越界返回 `unsafe_data`；schema 不匹配返回 `schema_mismatch`。失败不得伪装为成功或空 finding。
