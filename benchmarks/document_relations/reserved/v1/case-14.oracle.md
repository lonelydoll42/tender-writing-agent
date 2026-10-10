# Case 14 Oracle

独立按本文件原文语义标注；未读取产品输出。

## 原子条件
- A1：提交营业执照复印件。来源 P1-L02，原文：“提交营业执照复印件”。
- A2：提交等效资质证明。来源 P1-L03，原文：“提交等效资质证明”。
- A3：某一所选材料加盖公章。来源 P1-L04，原文：“该材料应加盖公章”；指代对象列为 candidate。

## 显式操作符
- OR(A1, A2)，满足其一即可：来源 P1-L01，原文：“满足下列任一条件即可”。
- AND：无显式 AND。

## 作用域
- S1 成员 A1、A2，二选一；依据 P1-L01“任一条件”。
- A3 对所选 A1 或 A2 的作用域为 candidate；原文没有明说“所选材料”。

## 关系
- parent / confirmed：A1、A2 属于“下列任一条件”；证据 P1-L01 与 P1-L02—P1-L03。
- parent / candidate：A3 可能修饰择一结果；证据 P1-L01“任一条件即可”及 P1-L04“该材料应加盖公章”。
- parent / unresolved：无法确认 A3 是分别适用于每个备选项，还是只适用于实际选中的一项；证据 P1-L02、P1-L03 两个备选材料及 P1-L04 单数指代“该材料”。
- scope / confirmed：A1、A2 同属 S1；证据 P1-L01：“下列任一条件即可”。
- scope / candidate：A3 可能约束择一后提交的材料；证据 P1-L04：“该材料应加盖公章”。
- scope / unresolved：A3 对 A1/A2 的覆盖方式未明确，不复制成两个 confirmed 要求；证据 P1-L02—P1-L04。
- reference / confirmed：无。
- reference / candidate：“该材料”可能回指实际选中的 A1 或 A2；证据 P1-L02、P1-L03 的备选项与 P1-L04“该材料”。
- reference / unresolved：文本未指出“该材料”具体对应哪个备选项；证据 P1-L02—P1-L04。

## 分母定义（冻结，未执行）
严格统计只计 confirmed 原子条件；candidate/unresolved 进入复核，不计自动判错。遗漏分母 N=2；错误合并分母为 N 个原子两两组合数；错误拆分分母 N；confirmed 作用域数 S=1，作用域误归属分母为 N × S 个 confirmed 原子—confirmed 作用域二元成员判断。A3 的指代/作用域进入复核，不进入严格分母。
