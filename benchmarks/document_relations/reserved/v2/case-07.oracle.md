# Case 07 Oracle

独立按本文件原文语义标注；未读取产品输出。

## 原子条件
- A1：提交营业执照。来源 P1-L01，原文：“营业执照”。
- A2：提交审计报告。来源 P1-L01，原文：“审计报告”。
- A3：提交纳税证明。来源 P2-L02，原文：“提交纳税证明”。

## 显式操作符
- AND(A1, A2, A3)：P1-L01 的“须全部提交”覆盖前两项；P2-L02 的“并须”在明确承接下追加 A3。
- OR：无。

## 作用域
- S1 成员 A1、A2、A3；依据 P1-L01“基本材料须全部提交”、P2-L01“承接上一页‘基本材料’清单”和 P2-L02“并须”。

## 关系
- parent / confirmed：A3 延续“基本材料”清单；证据 P2-L01：“承接上一页‘基本材料’清单”。
- parent / candidate：无。
- parent / unresolved：无。
- scope / confirmed：A1、A2、A3 属于同一基本材料提交范围；证据 P1-L01“基本材料须全部提交”及 P2-L01—P2-L02。
- scope / candidate：无。
- scope / unresolved：无。
- reference / confirmed：P2-L01 的“上一页‘基本材料’”明确回指 P1-L01 的基本材料范围；证据 P1-L01：“基本材料”及 P2-L01：“承接上一页‘基本材料’清单”。
- reference / candidate：无。
- reference / unresolved：无。

## 分母定义（冻结，未执行）
严格统计只计 confirmed 原子条件；candidate/unresolved 进入复核，不计自动判错。遗漏分母 N=3；错误合并分母为 N 个原子两两组合数；错误拆分分母 N；作用域误归属分母为 N × S 个 confirmed 原子—confirmed 作用域二元成员判断，S=1。无对应分母时记 N/A。
