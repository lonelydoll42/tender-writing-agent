# Benchmark Regression

这里记录每次版本必须通过的稳定回归入口：

- 旧评测与 TC01-TC09
- Tender V2 场景 A/B/C/D
- OCR、持久化、Artifact DAG 测试
- `baseline-v3-ocr.json` 中的冻结能力矩阵

Benchmark V3 challenge 不属于日常调参回归，只有版本节点才读取其答案并生成报告。
