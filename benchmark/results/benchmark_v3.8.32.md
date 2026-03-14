# DGC v3.8.32 Pre-Injection Benchmark

**Date:** 2026-03-14 14:25
**Prompts run:** 15
**Timeout:** 300s per prompt | **Cooldown:** 5s between runs

## Results Summary

| ID | Category | Normal Cost | MCP-DGC Cost | Pre-Inject Cost | Pre vs Normal | Pre vs MCP |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | code_explanation | $0.2654 | $0.1816 | $0.1648 | -37.9% | -9.3% |
| 2 | code_explanation | $0.2920 | $0.2494 | $0.1005 | -65.6% | -59.7% |
| 3 | code_explanation | $0.1275 | $0.1058 | $0.0634 | -50.3% | -40.1% |
| 4 | bug_fix | $0.0000 | $0.7069 | $0.2142 | N/A | -69.7% |
| 5 | bug_fix | $0.2638 | $0.2209 | $0.1159 | -56.1% | -47.5% |
| 6 | bug_fix | $0.0000 | $0.2348 | $0.0000 | N/A | N/A |
| 7 | feature_add | $0.2602 | $0.1729 | $0.0370 | -85.8% | -78.6% |
| 8 | feature_add | $0.1559 | $0.1388 | $0.0533 | -65.8% | -61.6% |
| 9 | feature_add | $0.2787 | $0.2166 | $0.1109 | -60.2% | -48.8% |
| 10 | refactoring | $0.1028 | $0.1388 | $0.1495 | +45.5% | +7.7% |
| 11 | refactoring | $0.1975 | $0.1267 | $0.2067 | +4.7% | +63.2% |
| 12 | architecture | $0.2959 | $0.3152 | $0.2559 | -13.5% | -18.8% |
| 13 | architecture | $0.3146 | $0.1590 | $0.1728 | -45.1% | +8.7% |
| 14 | debugging | $0.2927 | $0.1794 | $0.1034 | -64.7% | -42.4% |
| 15 | debugging | $0.1153 | $0.1243 | $0.0786 | -31.8% | -36.7% |

## Aggregate Statistics

| Metric | Normal | MCP-DGC | Pre-Inject |
| --- | --- | --- | --- |
| Total Cost (USD) | $2.9623 | $3.2710 | $1.8268 |
| Avg Cost (USD) | $0.1975 | $0.2181 | $0.1218 |
| Total Input Tokens | 1,877,642 | 2,887,144 | 1,655,912 |
| Total Output Tokens | 29,413 | 48,945 | 26,796 |
| Avg Wall Time (s) | 79.1 | 103.2 | 44.0 |
| Avg Turns | 7.7 | 10.5 | 6.5 |
| Avg Quality Score | 33.1/50 | 39.2/50 | 35.2/50 |
| Avg Pack Time (s) | --- | --- | 0.069 |
| Avg Pack Tokens | --- | --- | 2236 |

## Turn Count (Key Metric)

| ID | Normal Turns | MCP-DGC Turns | Pre-Inject Turns |
| --- | --- | --- | --- |
| 1 | 21 | 11 | 9 |
| 2 | 15 | 2 | 7 |
| 3 | 10 | 8 | 2 |
| 4 | 0 | 25 | 13 |
| 5 | 2 | 6 | 9 |
| 6 | 0 | 11 | 0 |
| 7 | 3 | 9 | 1 |
| 8 | 12 | 9 | 1 |
| 9 | 3 | 2 | 5 |
| 10 | 2 | 10 | 2 |
| 11 | 12 | 12 | 9 |
| 12 | 21 | 18 | 16 |
| 13 | 2 | 15 | 11 |
| 14 | 2 | 12 | 8 |
| 15 | 8 | 8 | 4 |

| **Average** | **7.7** | **10.5** | **6.5** |

## Category Breakdown

### Architecture

| Metric | Normal | MCP-DGC | Pre-Inject |
| --- | --- | --- | --- |
| Avg Cost | $0.3053 | $0.2371 | $0.2143 |
| Avg Turns | 11.5 | 16.5 | 13.5 |
| Avg Wall Time | 114.1s | 106.6s | 62.9s |
| Avg Quality | 35.5/50 | 40.0/50 | 38.5/50 |

### Bug Fix

| Metric | Normal | MCP-DGC | Pre-Inject |
| --- | --- | --- | --- |
| Avg Cost | $0.0879 | $0.3875 | $0.1100 |
| Avg Turns | 1.3 | 14.0 | 7.7 |
| Avg Wall Time | 66.7s | 149.5s | 39.4s |
| Avg Quality | 9.0/50 | 33.3/50 | 19.7/50 |

### Code Explanation

| Metric | Normal | MCP-DGC | Pre-Inject |
| --- | --- | --- | --- |
| Avg Cost | $0.2283 | $0.1789 | $0.1096 |
| Avg Turns | 15.3 | 7.0 | 6.0 |
| Avg Wall Time | 63.4s | 99.4s | 42.0s |
| Avg Quality | 40.7/50 | 42.7/50 | 39.3/50 |

### Debugging

| Metric | Normal | MCP-DGC | Pre-Inject |
| --- | --- | --- | --- |
| Avg Cost | $0.2040 | $0.1519 | $0.0910 |
| Avg Turns | 5.0 | 10.0 | 6.0 |
| Avg Wall Time | 76.7s | 76.1s | 36.6s |
| Avg Quality | 33.0/50 | 34.5/50 | 29.0/50 |

### Feature Add

| Metric | Normal | MCP-DGC | Pre-Inject |
| --- | --- | --- | --- |
| Avg Cost | $0.2316 | $0.1761 | $0.0670 |
| Avg Turns | 6.0 | 6.7 | 2.3 |
| Avg Wall Time | 93.5s | 94.2s | 29.7s |
| Avg Quality | 41.7/50 | 41.0/50 | 41.3/50 |

### Refactoring

| Metric | Normal | MCP-DGC | Pre-Inject |
| --- | --- | --- | --- |
| Avg Cost | $0.1501 | $0.1328 | $0.1781 |
| Avg Turns | 7.0 | 11.0 | 5.5 |
| Avg Wall Time | 66.8s | 76.7s | 63.5s |
| Avg Quality | 43.0/50 | 44.0/50 | 46.0/50 |

## Per-Prompt Details

### Prompt 1 — code_explanation
> Explain the restaurant onboarding flow end-to-end. Name the exact frontend pages, backend endpoints, and database models...

| Metric | Normal | MCP-DGC | Pre-Inject |
| --- | --- | --- | --- |
| Cost | $0.2654 | $0.1816 | $0.1648 |
| Input Tokens | 364,832 | 207,161 | 135,563 |
| Output Tokens | 4,231 | 2,680 | 2,461 |
| Cache Create | 26,801 | 22,964 | 25,267 |
| Cache Read | 338,016 | 184,187 | 110,289 |
| Turns | 21 | 11 | 9 |
| Wall Time | 81.8s | 83.5s | 51.9s |
| Quality | 46/50 | 44/50 | 40/50 |
| Pack Time | --- | --- | 0.030s |
| Pack Tokens | --- | --- | 2,838 |

### Prompt 2 — code_explanation
> Explain how customer authentication works in this codebase. Trace the flow from login form submission through token gene...

| Metric | Normal | MCP-DGC | Pre-Inject |
| --- | --- | --- | --- |
| Cost | $0.2920 | $0.2494 | $0.1005 |
| Input Tokens | 410,449 | 40,282 | 116,373 |
| Output Tokens | 3,111 | 1,413 | 1,870 |
| Cache Create | 35,416 | 8,065 | 10,884 |
| Cache Read | 375,019 | 32,213 | 105,482 |
| Turns | 15 | 2 | 7 |
| Wall Time | 72.1s | 141.8s | 45.0s |
| Quality | 38/50 | 43/50 | 40/50 |
| Pack Time | --- | --- | 0.039s |
| Pack Tokens | --- | --- | 2,397 |

### Prompt 3 — code_explanation
> Explain the WhatsApp webhook integration. How does an incoming WhatsApp message get processed, stored, and trigger notif...

| Metric | Normal | MCP-DGC | Pre-Inject |
| --- | --- | --- | --- |
| Cost | $0.1275 | $0.1058 | $0.0634 |
| Input Tokens | 140,307 | 108,648 | 44,572 |
| Output Tokens | 1,752 | 1,913 | 1,098 |
| Cache Create | 17,144 | 12,909 | 9,724 |
| Cache Read | 123,155 | 95,732 | 34,844 |
| Turns | 10 | 8 | 2 |
| Wall Time | 36.2s | 72.9s | 29.1s |
| Quality | 38/50 | 41/50 | 38/50 |
| Pack Time | --- | --- | 0.048s |
| Pack Tokens | --- | --- | 2,621 |

### Prompt 4 — bug_fix
> A restaurant owner reports that updating their location on the settings page silently fails — the form submits but the o...

| Metric | Normal | MCP-DGC | Pre-Inject |
| --- | --- | --- | --- |
| Cost | $0.0000 | $0.7069 | $0.2142 |
| Input Tokens | 0 | 842,025 | 335,416 |
| Output Tokens | 0 | 16,919 | 2,922 |
| Cache Create | 0 | 56,738 | 20,192 |
| Cache Read | 0 | 783,541 | 315,211 |
| Turns | 0 | 25 | 13 |
| Wall Time | 0.0s | 299.8s | 78.7s |
| Quality | 0/50 | 35/50 | 27/50 |
| Pack Time | --- | --- | 0.059s |
| Pack Tokens | --- | --- | 2,680 |

### Prompt 5 — bug_fix
> Customers report that their order history page sometimes shows orders from other customers. Identify the most likely bac...

| Metric | Normal | MCP-DGC | Pre-Inject |
| --- | --- | --- | --- |
| Cost | $0.2638 | $0.2209 | $0.1159 |
| Input Tokens | 16,446 | 118,387 | 144,638 |
| Output Tokens | 377 | 2,518 | 1,848 |
| Cache Create | 2,160 | 42,775 | 12,982 |
| Cache Read | 14,283 | 75,606 | 131,648 |
| Turns | 2 | 6 | 9 |
| Wall Time | 200.1s | 77.3s | 39.6s |
| Quality | 27/50 | 40/50 | 32/50 |
| Pack Time | --- | --- | 0.103s |
| Pack Tokens | --- | --- | 1,386 |

### Prompt 6 — bug_fix
> The admin dashboard analytics endpoint returns a 500 error when a restaurant has zero orders. Trace the analytics calcul...

| Metric | Normal | MCP-DGC | Pre-Inject |
| --- | --- | --- | --- |
| Cost | $0.0000 | $0.2348 | $0.0000 |
| Input Tokens | 0 | 245,733 | 0 |
| Output Tokens | 0 | 1,939 | 0 |
| Cache Create | 0 | 37,916 | 0 |
| Cache Read | 0 | 207,361 | 0 |
| Turns | 0 | 11 | 0 |
| Wall Time | 0.0s | 71.4s | 0.0s |
| Quality | 0/50 | 25/50 | 0/50 |
| Pack Time | --- | --- | 0.000s |
| Pack Tokens | --- | --- | 0 |

### Prompt 7 — feature_add
> Design a restaurant menu item bulk import feature that accepts a CSV file. List which existing files need modification, ...

| Metric | Normal | MCP-DGC | Pre-Inject |
| --- | --- | --- | --- |
| Cost | $0.2602 | $0.1729 | $0.0370 |
| Input Tokens | 43,839 | 155,972 | 20,205 |
| Output Tokens | 1,319 | 1,766 | 700 |
| Cache Create | 13,103 | 28,874 | 5,913 |
| Cache Read | 30,731 | 127,091 | 14,289 |
| Turns | 3 | 9 | 1 |
| Wall Time | 101.8s | 78.6s | 20.2s |
| Quality | 41/50 | 40/50 | 36/50 |
| Pack Time | --- | --- | 0.111s |
| Pack Tokens | --- | --- | 2,245 |

### Prompt 8 — feature_add
> Design a customer loyalty points system. Identify where points should be earned (order completion), stored (database mod...

| Metric | Normal | MCP-DGC | Pre-Inject |
| --- | --- | --- | --- |
| Cost | $0.1559 | $0.1388 | $0.0533 |
| Input Tokens | 179,362 | 130,822 | 9,613 |
| Output Tokens | 2,447 | 2,128 | 1,149 |
| Cache Create | 18,942 | 19,584 | 9,610 |
| Cache Read | 160,411 | 111,231 | 0 |
| Turns | 12 | 9 | 1 |
| Wall Time | 53.4s | 74.6s | 28.3s |
| Quality | 40/50 | 39/50 | 44/50 |
| Pack Time | --- | --- | 0.186s |
| Pack Tokens | --- | --- | 2,044 |

### Prompt 9 — feature_add
> Design a real-time order tracking feature for the customer portal. Identify the existing WebSocket infrastructure, the o...

| Metric | Normal | MCP-DGC | Pre-Inject |
| --- | --- | --- | --- |
| Cost | $0.2787 | $0.2166 | $0.1109 |
| Input Tokens | 54,003 | 38,831 | 79,997 |
| Output Tokens | 1,495 | 1,236 | 1,467 |
| Cache Create | 6,610 | 6,610 | 18,797 |
| Cache Read | 47,388 | 32,217 | 61,195 |
| Turns | 3 | 2 | 5 |
| Wall Time | 125.2s | 129.3s | 40.5s |
| Quality | 44/50 | 44/50 | 44/50 |
| Pack Time | --- | --- | 0.075s |
| Pack Tokens | --- | --- | 2,221 |

### Prompt 10 — refactoring
> The API client code is duplicated across the restaurant portal and customer portal. Identify all API client/helper files...

| Metric | Normal | MCP-DGC | Pre-Inject |
| --- | --- | --- | --- |
| Cost | $0.1028 | $0.1388 | $0.1495 |
| Input Tokens | 34,960 | 133,443 | 44,042 |
| Output Tokens | 1,381 | 1,972 | 1,385 |
| Cache Create | 4,230 | 20,049 | 8,958 |
| Cache Read | 30,726 | 113,387 | 35,080 |
| Turns | 2 | 10 | 2 |
| Wall Time | 68.5s | 72.0s | 69.7s |
| Quality | 42/50 | 44/50 | 46/50 |
| Pack Time | --- | --- | 0.060s |
| Pack Tokens | --- | --- | 3,006 |

### Prompt 11 — refactoring
> Identify all authentication-related middleware in the backend. Are there redundant auth checks? Propose a consolidated m...

| Metric | Normal | MCP-DGC | Pre-Inject |
| --- | --- | --- | --- |
| Cost | $0.1975 | $0.1267 | $0.2067 |
| Input Tokens | 213,713 | 155,906 | 183,236 |
| Output Tokens | 3,855 | 2,579 | 2,893 |
| Cache Create | 21,887 | 11,948 | 31,407 |
| Cache Read | 191,816 | 143,949 | 151,822 |
| Turns | 12 | 12 | 9 |
| Wall Time | 65.2s | 81.4s | 57.4s |
| Quality | 44/50 | 44/50 | 46/50 |
| Pack Time | --- | --- | 0.052s |
| Pack Tokens | --- | --- | 2,367 |

### Prompt 12 — architecture
> Evaluate the current database model structure. Identify all SQLAlchemy models, their relationships, and any missing inde...

| Metric | Normal | MCP-DGC | Pre-Inject |
| --- | --- | --- | --- |
| Cost | $0.2959 | $0.3152 | $0.2559 |
| Input Tokens | 231,609 | 227,725 | 202,516 |
| Output Tokens | 5,101 | 5,200 | 3,428 |
| Cache Create | 40,003 | 48,938 | 41,647 |
| Cache Read | 187,188 | 178,778 | 160,861 |
| Turns | 21 | 18 | 16 |
| Wall Time | 76.1s | 114.0s | 68.0s |
| Quality | 39/50 | 39/50 | 42/50 |
| Pack Time | --- | --- | 0.051s |
| Pack Tokens | --- | --- | 1,575 |

### Prompt 13 — architecture
> Map the complete notification system architecture. How do notifications get created, stored, delivered (push/websocket/e...

| Metric | Normal | MCP-DGC | Pre-Inject |
| --- | --- | --- | --- |
| Cost | $0.3146 | $0.1590 | $0.1728 |
| Input Tokens | 38,152 | 197,860 | 173,620 |
| Output Tokens | 1,268 | 2,828 | 2,448 |
| Cache Create | 7,421 | 16,315 | 24,346 |
| Cache Read | 30,727 | 181,214 | 149,266 |
| Turns | 2 | 15 | 11 |
| Wall Time | 152.1s | 99.2s | 57.8s |
| Quality | 32/50 | 41/50 | 35/50 |
| Pack Time | --- | --- | 0.048s |
| Pack Tokens | --- | --- | 2,354 |

### Prompt 14 — debugging
> The restaurant portal loads slowly on initial page load. Identify the main data-fetching hooks, their API calls, and whi...

| Metric | Normal | MCP-DGC | Pre-Inject |
| --- | --- | --- | --- |
| Cost | $0.2927 | $0.1794 | $0.1034 |
| Input Tokens | 38,116 | 180,390 | 97,629 |
| Output Tokens | 1,274 | 2,184 | 1,665 |
| Cache Create | 7,381 | 26,824 | 14,224 |
| Cache Read | 30,731 | 153,558 | 83,399 |
| Turns | 2 | 12 | 8 |
| Wall Time | 109.1s | 79.6s | 38.1s |
| Quality | 31/50 | 39/50 | 33/50 |
| Pack Time | --- | --- | 0.109s |
| Pack Tokens | --- | --- | 2,792 |

### Prompt 15 — debugging
> WebSocket connections are dropping intermittently for restaurant users. Identify the WebSocket setup code in both fronte...

| Metric | Normal | MCP-DGC | Pre-Inject |
| --- | --- | --- | --- |
| Cost | $0.1153 | $0.1243 | $0.0786 |
| Input Tokens | 111,854 | 103,959 | 68,492 |
| Output Tokens | 1,802 | 1,670 | 1,462 |
| Cache Create | 15,863 | 19,715 | 10,470 |
| Cache Read | 95,984 | 84,238 | 58,017 |
| Turns | 8 | 8 | 4 |
| Wall Time | 44.2s | 72.5s | 35.1s |
| Quality | 35/50 | 30/50 | 25/50 |
| Pack Time | --- | --- | 0.057s |
| Pack Tokens | --- | --- | 3,009 |

---
*Generated by run_preinjection_benchmark.py v3.8.32*
