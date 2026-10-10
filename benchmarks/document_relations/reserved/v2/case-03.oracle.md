# Case 03 Oracle

独立按本文件原文语义标注；未读取产品输出。

## 原子条件
- A1：提交营业执照复印件。来源 P1-L02，原文：“营业执照复印件”。
- A2：提交资质证书。来源 P1-L02，原文：“资质证书”。
- A3：提交项目负责人授权书。来源 P1-L03，原文：“项目负责人授权书”。

## 显式操作符
- OR(A1, A2)，基数恰为 1：来源 P1-L02，原文：“第一组任选其一”。
- AND(S1, A3)：来源 P1-L01，原文：“两组要求均须满足”；S1 为第一组选择结果，A3 为第二组要求。

## 作用域
- S1 成员 A1、A2，二选一；依据 P1-L02“第一组任选其一”。
- S2 成员 A3；依据 P1-L03“第二组必须提交”。
- S0 成员 S1、A3；依据 P1-L01“两组要求均须满足”。

## 关系
- parent / confirmed：第一组统领 A1、A2，第二组统领 A3；证据分别为 P1-L02“第一组任选其一”和 P1-L03“第二组必须提交”。
- parent / candidate：无。
- parent / unresolved：无。
- scope / confirmed：S1 与 S2 是不同分组，且两组都纳入 S0；证据 P1-L01“两组要求均须满足”及 P1-L02“第一组”、P1-L03“第二组”。
- scope / candidate：无。
- scope / unresolved：无。
- reference / confirmed：无。
- reference / candidate：无。
- reference / unresolved：无；本例没有回指表达。

## 分母定义（冻结，未执行）
严格统计只计 confirmed 原子条件；candidate/unresolved 进入复核，不计自动判错。遗漏分母 N=3；错误合并分母为 N 个原子两两组合数；错误拆分分母 N；作用域误归属分母为 N × S 个 confirmed 原子—confirmed 作用域二元成员判断，S=3（S0、S1、S2）。无对应分母时记 N/A。
