# Case 12 Oracle

独立按本文件原文语义标注；未读取产品输出。

## 原子条件
- A1：提交编号 1.9 项材料。来源 P1-L01，原文：“编号1.9项”。
- A2：提交编号 1.10 项材料。来源 P1-L01，原文：“编号1.10项”。

## 显式操作符
- AND(A1, A2)：来源 P1-L01，原文：“共两项材料均须提交”。
- OR：无。
- “至”连接的是明确标注为材料编号的两个标签；原文又明确限定为两项，不按小数值区间扩展。

## 作用域
- S1 成员 A1、A2；依据 P1-L01“编号1.9至1.10”及“共两项材料均须提交”。

## 关系
- parent / confirmed：两项材料均由同一编号范围句统领；证据 P1-L01：“编号1.9至1.10……共两项材料均须提交”。
- parent / candidate：无。
- parent / unresolved：无。
- scope / confirmed：编号 1.9、1.10 两项共同属于 S1；证据 P1-L01：“编号1.9项和编号1.10项，共两项材料均须提交”。
- scope / candidate：无。
- scope / unresolved：无。
- reference / confirmed：无；编号标签不是 discourse 回指。
- reference / candidate：无。
- reference / unresolved：无。

## 分母定义（冻结，未执行）
严格统计只计 confirmed 原子条件；candidate/unresolved 进入复核，不计自动判错。遗漏分母 N=2；错误合并分母为 N 个原子两两组合数；错误拆分分母 N；作用域误归属分母为 N × S 个 confirmed 原子—confirmed 作用域二元成员判断，S=1。无对应分母时记 N/A。
