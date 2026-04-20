# 注册成功率历史分析报告

## 分析口径

- 分析窗口：全量历史，原始 UTC 记录跨度 `2026-04-16 20:01:51` 到 `2026-04-20 05:28:02`。
- 展示时区：`Asia/Shanghai`，图表/分组按本地时区展示，CSV 保留原始 UTC 字段。
- 主成功率口径：`unknown_policy = exclude`，即 `final_status = unknown` 不进入主成功率分母，但单独展示 unknown 数量与占比。
- Token 等待主窗口：从 `2026-04-19 07:08:50` 开始；`2026-04-18` 被标记为过渡期，不和等待时长窗口混算。

## 总览

- 总尝试数：10515
- 已完结数：8726
- 成功数：1520
- 失败数：7206
- Unknown 数：1789
- Closed 成功率：17.42%
- Unknown 占比：17.01%
- 已注册待最终 Token：7468
- 已进入 Token 等待：6145

## 成功率随时间分布

| 日期 | 样本 | 成功 | Closed 成功率 | Unknown 占比 | 已注册 | 已等待 | 过渡期样本 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 2026-04-17 | 19 | 19 | 100.00% | 0.00% | 0 | 0 | 0 |
| 2026-04-18 | 1220 | 432 | 37.63% | 5.90% | 642 | 0 | 1147 |
| 2026-04-19 | 4456 | 555 | 15.37% | 18.94% | 3018 | 2337 | 947 |
| 2026-04-20 | 4820 | 514 | 13.02% | 18.11% | 3808 | 3808 | 0 |


### 小时分布（前 12 个高样本小时）

| 小时 | 样本 | 成功 | Closed 成功率 | Unknown 占比 |
| --- | --- | --- | --- | --- |
| 2026-04-18 06 | 26 | 26 | 100.00% | 0.00% |
| 2026-04-18 07 | 22 | 22 | 100.00% | 0.00% |
| 2026-04-18 03 | 10 | 10 | 100.00% | 0.00% |
| 2026-04-17 19 | 6 | 6 | 100.00% | 0.00% |
| 2026-04-18 02 | 6 | 6 | 100.00% | 0.00% |
| 2026-04-18 05 | 6 | 6 | 100.00% | 0.00% |
| 2026-04-17 20 | 4 | 4 | 100.00% | 0.00% |
| 2026-04-17 21 | 4 | 4 | 100.00% | 0.00% |
| 2026-04-17 17 | 3 | 3 | 100.00% | 0.00% |
| 2026-04-18 04 | 3 | 3 | 100.00% | 0.00% |
| 2026-04-17 04 | 1 | 1 | 100.00% | 0.00% |
| 2026-04-17 16 | 1 | 1 | 100.00% | 0.00% |


### Run 分布（前 10 个高样本 Run）

| Run | 样本 | 成功 | Closed 成功率 | Unknown 占比 | 等待配置 |
| --- | --- | --- | --- | --- | --- |
| 42 | 4820 | 514 | 13.02% | 18.11% | 30-90 |
| 41 | 2180 | 348 | 16.60% | 3.85% | 30-90 |
| 38 | 1290 | 75 | 9.72% | 40.16% | None-None |
| 18 | 480 | 109 | 24.49% | 7.29% | None-None |
| 17 | 430 | 100 | 24.39% | 4.65% | None-None |
| 40 | 340 | 52 | 16.83% | 9.12% | 30-90 |
| 0 | 260 | 260 | 100.00% | 0.00% | None-None |
| 36 | 120 | 13 | 13.27% | 18.33% | None-None |
| 37 | 120 | 18 | 18.56% | 19.17% | None-None |
| 27 | 100 | 0 | 0.00% | 8.00% | None-None |


## IP 与出口分布

### Proxy Top 10

| Proxy | 样本 | 成功 | Closed 成功率 | Unknown 占比 | 累计占比 |
| --- | --- | --- | --- | --- | --- |
| (空) | 535 | 43 | 97.73% | 91.78% | 5.09% |
| 🇭🇰 香港W06 \| x0.8 | 381 | 53 | 15.45% | 9.97% | 8.71% |
| 🇭🇰 香港W07 \| x0.8 | 362 | 59 | 17.10% | 4.70% | 12.15% |
| 🇯🇵 日本W03 \| IEPL | 361 | 65 | 21.10% | 14.68% | 15.59% |
| 🇭🇰 香港W01 | 348 | 51 | 15.69% | 6.61% | 18.90% |
| 🇭🇰 香港W08 \| x0.8 | 347 | 66 | 20.82% | 8.65% | 22.20% |
| 🇸🇬 新加坡W03 \| IEPL \| x2 | 344 | 39 | 13.98% | 18.90% | 25.47% |
| 🇭🇰 香港W03 \| IEPL | 341 | 44 | 14.97% | 13.78% | 28.71% |
| 🇭🇰 香港W02 \| IEPL | 335 | 57 | 19.26% | 11.64% | 31.90% |
| 🇯🇵 日本W11 \| IEPL | 334 | 49 | 16.72% | 12.28% | 35.07% |


### Exit IP Top 10

| Exit IP | 样本 | 成功 | Closed 成功率 | Unknown 占比 | 累计占比 |
| --- | --- | --- | --- | --- | --- |
| (空) | 1794 | 260 | 100.00% | 85.51% | 17.06% |
| 43.243.192.91 | 344 | 44 | 13.21% | 3.20% | 20.33% |
| 43.243.192.92 | 341 | 50 | 14.88% | 1.47% | 23.58% |
| 141.11.146.74 | 340 | 48 | 14.86% | 5.00% | 26.81% |
| 43.243.192.97 | 320 | 60 | 19.29% | 2.81% | 29.85% |
| 103.151.173.90 | 297 | 42 | 14.69% | 3.70% | 32.68% |
| 149.102.240.84 | 290 | 55 | 19.50% | 2.76% | 35.44% |
| 103.151.173.210 | 284 | 46 | 16.49% | 1.76% | 38.14% |
| 146.70.184.22 | 279 | 40 | 15.09% | 5.02% | 40.79% |
| 103.216.220.39 | 278 | 37 | 13.81% | 3.60% | 43.43% |


### Country Top 10

| 国家 | 样本 | 成功 | Closed 成功率 | Unknown 占比 | 累计占比 |
| --- | --- | --- | --- | --- | --- |
| Hong Kong | 2796 | 407 | 15.01% | 3.00% | 26.59% |
| Japan | 2466 | 360 | 15.03% | 2.84% | 50.04% |
| (空) | 1794 | 260 | 100.00% | 85.51% | 67.10% |
| United States | 835 | 97 | 11.92% | 2.51% | 75.05% |
| Singapore | 736 | 103 | 14.35% | 2.45% | 82.04% |
| Ukraine | 290 | 55 | 19.50% | 2.76% | 84.80% |
| France | 279 | 40 | 15.09% | 5.02% | 87.46% |
| Australia | 278 | 37 | 13.81% | 3.60% | 90.10% |
| Canada | 277 | 34 | 12.55% | 2.17% | 92.73% |
| Germany | 272 | 53 | 20.08% | 2.94% | 95.32% |


## Token 等待时间分布

| 等待桶 | 样本 | 成功 | Closed 成功率 | Unknown 占比 |
| --- | --- | --- | --- | --- |
| 30-44s | 1505 | 225 | 14.95% | 0.00% |
| 45-59s | 1518 | 217 | 14.30% | 0.00% |
| 60-74s | 1497 | 242 | 16.18% | 0.07% |
| 75-89s | 1539 | 218 | 14.17% | 0.00% |
| >=90s | 86 | 12 | 13.95% | 0.00% |


### Token 等待分组摘要（前 12 条）

| 维度 | 分组 | 样本 | 平均等待(s) | P50(s) | Closed 成功率 | 越界数 |
| --- | --- | --- | --- | --- | --- | --- |
| run_id | 42 | 3808 | 60.01 | 60.0 | 13.50% | 0 |
| run_id | 41 | 2040 | 60.09 | 60.0 | 17.06% | 0 |
| geo_country_name | Hong Kong | 1923 | 59.59 | 60.0 | 15.03% | 0 |
| geo_country_name | Japan | 1778 | 60.11 | 60.0 | 14.58% | 0 |
| geo_country_name | United States | 594 | 59.18 | 58.0 | 11.62% | 0 |
| geo_country_name | Singapore | 508 | 60.2 | 61.0 | 15.35% | 0 |
| started_hour_local | 2026-04-19 16 | 398 | 60.77 | 62.5 | 18.09% | 0 |
| started_hour_local | 2026-04-19 19 | 394 | 61.23 | 62.0 | 17.26% | 0 |
| started_hour_local | 2026-04-20 02 | 378 | 60.51 | 60.0 | 17.46% | 0 |
| started_hour_local | 2026-04-19 17 | 377 | 59.1 | 58.0 | 16.45% | 0 |
| started_hour_local | 2026-04-20 03 | 372 | 61.01 | 64.0 | 16.67% | 0 |
| started_hour_local | 2026-04-20 04 | 369 | 60.75 | 61.0 | 18.43% | 0 |


## 注册漏斗与中间态

| 阶段 | 数量 | 环比转化 | 总转化 |
| --- | --- | --- | --- |
| 总尝试 | 10515 | 100.00% | 100.00% |
| 拿到邮箱 | 8847 | 84.14% | 84.14% |
| 命中手机号门槛 | 7463 | 84.36% | 70.97% |
| 已注册待最终 Token | 7468 | 100.07% | 71.02% |
| 已进入 Token 等待 | 6145 | 82.28% | 58.44% |
| 最终成功 | 1520 | 24.74% | 14.46% |


- 已注册但未等待：1323
- 已等待但未成功：5231
- 未完结 unknown：1789

## 失败与卡点归因

| failure_stage | failure_code | HTTP | 样本 | Unknown 占比 |
| --- | --- | --- | --- | --- |
| oauth_trace | (空) | (空) | 5634 | 0.00% |
| (空) | (空) | (空) | 3578 | 50.00% |
| main_exception | (空) | (空) | 491 | 0.00% |
| oauth_takeover_validate_otp | (空) | 401 | 281 | 0.00% |
| takeover_validate_otp | (空) | 403 | 236 | 0.00% |
| register_phone_gate | (空) | (空) | 198 | 0.00% |
| create_account | user_already_exists | 400 | 52 | 0.00% |
| takeover_validate_otp | (空) | 401 | 28 | 0.00% |
| create_account | unsupported_email | 400 | 4 | 0.00% |
| oauth_takeover_validate_otp | (空) | 502 | 3 | 0.00% |


### 高频事件路径

| 路径 | 出现次数 |
| --- | --- |
| attempt_started > proxy_bound > exit_ip_resolved > email_acquired > phone_gate_hit > token_wait_scheduled > account_registered_pending_token > attempt_finished | 5102 |
| attempt_started > proxy_bound | 1052 |
| attempt_started > proxy_bound > exit_ip_resolved > email_acquired > phone_gate_hit > account_registered_pending_token > attempt_finished | 915 |
| attempt_started | 482 |
| attempt_started > proxy_bound > exit_ip_resolved > email_acquired > attempt_finished | 476 |
| attempt_started > proxy_bound > exit_ip_resolved > email_acquired > phone_gate_hit > attempt_finished | 474 |
| attempt_started > proxy_bound > exit_ip_resolved > email_acquired > phone_gate_hit > token_wait_scheduled > account_registered_pending_token > account_create_completed > oauth_callback_submitted > token_received > attempt_finished | 401 |
| attempt_started > proxy_bound > exit_ip_resolved > email_acquired > account_create_completed > token_wait_scheduled > account_registered_pending_token > oauth_callback_submitted > token_received > attempt_finished | 261 |
| attempt_started > proxy_bound > exit_ip_resolved > email_acquired > phone_gate_hit > account_create_completed > token_wait_scheduled > account_registered_pending_token > oauth_callback_submitted > token_received > attempt_finished | 250 |
| attempt_finished | 199 |


## 数据质量与覆盖审计

- legacy backfill 记录数：199
- 缺失 exit_ip 记录数：1794
- 缺失 geo 记录数：1794
- 没有 finished_at 的记录数：1789
- 覆盖过渡期（2026-04-18）记录数：2094

## Top / Bottom 段摘录

| 维度 | 方向 | 分组 | 样本 | Closed 成功率 |
| --- | --- | --- | --- | --- |
| exit_ip | bottom | 222.120.184.101 | 32 | 6.25% |
| exit_ip | bottom | 103.151.172.95 | 40 | 7.69% |
| exit_ip | bottom | 222.120.184.105 | 36 | 8.57% |
| exit_ip | bottom | 103.151.173.95 | 34 | 9.68% |
| exit_ip | bottom | 103.151.172.89 | 50 | 10.00% |
| exit_ip | top | 222.120.184.139 | 30 | 23.33% |
| exit_ip | top | 146.70.117.59 | 272 | 20.08% |
| exit_ip | top | 149.102.240.84 | 290 | 19.50% |
| exit_ip | top | 43.243.192.97 | 320 | 19.29% |
| exit_ip | top | 84.245.9.146 | 36 | 18.18% |
| geo_country_name | bottom | United States | 835 | 11.92% |
| geo_country_name | bottom | Canada | 277 | 12.55% |

