# Case 02 Oracle

独立按本文件原文语义标注；未读取产品输出。

## 原子条件
- A1：提交银行资信证明。来源 P1-L01，原文：“银行资信证明”。
- A2：提交纳税信用证明。来源 P1-L01，原文：“纳税信用证明”。
- A3：提交信用等级报告。来源 P1-L01，原文：“信用等级报告”。

## 显式操作符
- OR(A1, A2, A3)，基数恰为 1：来源 P1-L01，原文：“以下任一项作为资信证明即可，三项中任选一项”。
- AND：无。

## 作用域
- S1 成员 A1、A2、A3，三选一；依据 P1-L01“以下任一项……三项中任选一项”。

## 关系
- parent / confirmed：统领语“资信证明”涵盖 A1、A2、A3；证据 P1-L01：“以下任一项作为资信证明即可”。
- parent / candidate：无。
- parent / unresolved：无。
- scope / confirmed：A1、A2、A3 同属 S1 且基数为 1；证据 P1-L01：“三项中任选一项”。
- scope / candidate：无。
- scope / unresolved：无。
- reference / confirmed：无。
- reference / candidate：无。
- reference / unresolved：无；本例没有回指表达。

## 分母定义（冻结，未执行）
严格统计只计 confirmed 原子条件；candidate/unresolved 进入复核，不计自动判错。遗漏分母 N=3；错误合并分母为 N 个原子两两组合数；错误拆分分母 N；作用域误归属分母为 N × S 个 confirmed 原子—confirmed 作用域二元成员判断，S=1。无对应分母时记 N/A。
