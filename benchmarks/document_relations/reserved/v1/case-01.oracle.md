# Case 01 Oracle

独立按本文件原文语义标注；未读取产品输出。

## 原子条件
- A1：提交营业执照。来源 P1-L01，原文：“提交营业执照”。
- A2：提交近一年度财务报表。来源 P1-L01，原文：“近一年度财务报表”。

## 显式操作符
- AND(A1, A2)：来源 P1-L01，原文：“均须同时提交营业执照及近一年度财务报表”。
- OR：无。

## 作用域
- S1 成员 A1、A2；依据 P1-L01“资格材料均须同时提交”。

## 关系
- parent / confirmed：资格材料这一统领语适用于 A1、A2；证据 P1-L01：“资格材料均须同时提交营业执照及近一年度财务报表”。
- parent / candidate：无。
- parent / unresolved：无。
- scope / confirmed：A1、A2 同属 S1；证据 P1-L01：“均须同时提交”。
- scope / candidate：无。
- scope / unresolved：无。
- reference / confirmed：无。
- reference / candidate：无。
- reference / unresolved：无；本例没有回指表达。

## 分母定义（冻结，未执行）
严格统计只计 confirmed 原子条件；candidate/unresolved 进入复核，不计自动判错。遗漏分母 N=2；错误合并分母为 N 个原子两两组合数；错误拆分分母 N；作用域误归属分母为 N × S 个 confirmed 原子—confirmed 作用域二元成员判断，S=1。无对应分母时记 N/A。
