# Case 09 Oracle

独立按本文件原文语义标注；未读取产品输出。

## 原子条件
- A1：提交法定代表人身份证复印件。来源 P1-L01，原文：“提交法定代表人身份证复印件”。
- A2：该身份证复印件加盖公章。来源 P1-L02，原文：“该复印件必须加盖公章”。

## 显式操作符
- AND：无枚举式显式 AND；A2 是对 A1 所指文件增加的明确属性要求，不据此拆成无关材料。
- OR：无。

## 作用域
- S1 成员 A1、A2；A2 的对象是 A1 所指复印件。依据 P1-L01—P1-L02 的相邻单一名词先行项及“该复印件”。

## 关系
- parent / confirmed：加盖公章要求修饰 A1 的复印件；证据 P1-L01：“法定代表人身份证复印件”及 P1-L02：“该复印件必须加盖公章”。
- parent / candidate：无。
- parent / unresolved：无。
- scope / confirmed：A2 作用于 A1 指向的同一复印件；证据 P1-L02：“该复印件”。
- scope / candidate：无。
- scope / unresolved：无。
- reference / confirmed：“该复印件”唯一回指 P1-L01 的“法定代表人身份证复印件”；证据 P1-L01、P1-L02。
- reference / candidate：无。
- reference / unresolved：无。

## 分母定义（冻结，未执行）
严格统计只计 confirmed 原子条件；candidate/unresolved 进入复核，不计自动判错。遗漏分母 N=2；错误合并分母为 N 个原子两两组合数；错误拆分分母 N；作用域误归属分母为 N × S 个 confirmed 原子—confirmed 作用域二元成员判断，S=1。无对应分母时记 N/A。
