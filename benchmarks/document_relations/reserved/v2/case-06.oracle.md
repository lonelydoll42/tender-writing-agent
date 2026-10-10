# Case 06 Oracle

独立按本文件原文语义标注；未读取产品输出。

## 原子条件
- A1：提交营业执照。来源 P1-L01，原文：“提交营业执照”。
- A2：提交财务报表。来源 P1-L01，原文：“财务报表”。
- A3：提交纳税证明。来源 P1-L03，原文：“纳税证明”。
- A4：提交审计报告。来源 P1-L04，原文：“审计报告”。

## 显式操作符
- AND(A1, A2)：来源 P1-L01，原文：“须同时提交营业执照及财务报表”。
- OR(A3, A4)，基数恰为 1：来源 P1-L02，原文：“补充证明可任选一项”。

## 作用域
- S1 成员 A1、A2；依据 P1-L01“一、必交资格材料”及“须同时提交”。
- S2 成员 A3、A4；依据 P1-L02“二、补充证明可任选一项”。
- S1 与 S2 是分开的作用域；编号切换本身不是 AND 依据。

## 关系
- parent / confirmed：第一节统领 A1、A2，第二节统领 A3、A4；证据 P1-L01“一、必交资格材料”和 P1-L02“二、补充证明”。
- parent / candidate：无。
- parent / unresolved：无。
- scope / confirmed：S1 与 S2 分别承载不同操作符；证据 P1-L01“须同时提交”与 P1-L02“可任选一项”。
- scope / candidate：无。
- scope / unresolved：无。
- reference / confirmed：无。
- reference / candidate：无。
- reference / unresolved：无；本例没有回指表达。

## 分母定义（冻结，未执行）
严格统计只计 confirmed 原子条件；candidate/unresolved 进入复核，不计自动判错。遗漏分母 N=4；错误合并分母为 N 个原子两两组合数；错误拆分分母 N；作用域误归属分母为 N × S 个 confirmed 原子—confirmed 作用域二元成员判断，S=2。无对应分母时记 N/A。
