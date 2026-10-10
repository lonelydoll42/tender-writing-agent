# Case 08 Oracle

独立按本文件原文语义标注；未读取产品输出。

## 原子条件
- A1：提交营业执照。来源 P1-L01，原文：“营业执照”。
- A2：提交审计报告。来源 P1-L01，原文：“审计报告”。
- A3：可能要求提交项目联系人表，但该页片段没有谓语或承接标记，列为 candidate 原子条件，不作确定性要求。来源 P2-L01，原文：“项目联系人表一份”。

## 显式操作符
- AND(A1, A2)：来源 P1-L01，原文：“基本材料须同时提交：营业执照、审计报告”。
- OR：无。
- P2-L01 未出现“续”“另须”或其他可确认与 P1-L01 逻辑相连的操作符。

## 作用域
- S1 confirmed 成员 A1、A2；依据 P1-L01“基本材料须同时提交”。
- A3 是否属于 S1 未确认；P2-L01 没有明确的跨页延续语。

## 关系
- parent / confirmed：P1-L01 的“基本材料”统领 A1、A2；证据 P1-L01：“本页基本材料须同时提交”。
- parent / candidate：A3 可能是续列材料；证据为相邻页的 P1-L01“基本材料”与 P2-L01“项目联系人表一份”，但无承接措辞。
- parent / unresolved：无法确定 P2-L01 是前页清单续项还是独立片段；证据 P1-L01 与 P2-L01，两页之间没有显式承接文字。
- scope / confirmed：A1、A2 同属 S1；证据 P1-L01：“须同时提交”。
- scope / candidate：A3 可能属于 S1；证据 P1-L01“基本材料”与 P2-L01“项目联系人表一份”。
- scope / unresolved：A3 与 S1 的成员关系未定；P2-L01 没有延续、另列或提交要求用语。
- reference / confirmed：无。
- reference / candidate：无。
- reference / unresolved：无；本例没有回指表达。

## 分母定义（冻结，未执行）
严格统计只计 confirmed 原子条件；candidate/unresolved 进入复核，不计自动判错。遗漏分母 N=2；错误合并分母为 N 个原子两两组合数；错误拆分分母 N；confirmed 作用域数 S=1，作用域误归属分母为 N × S 个 confirmed 原子—confirmed 作用域二元成员判断。A3 不进入严格分母。
