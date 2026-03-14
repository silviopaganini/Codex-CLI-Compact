# DGC v3.8.33 Challenge Benchmark

**Date:** 2026-03-14 17:29
**Prompts:** 10 complex cross-cutting queries
**Budget:** 5000 tokens | **Timeout:** 600s | **Model:** claude-sonnet-4-6
**Mode:** Normal Claude (all tools) vs Pre-Injection v3.8.33 (packed context + all tools)

## Native Tools Available (Both Modes)
- **Read** — read files with offset/limit
- **Grep** — ripgrep-powered content search
- **Glob** — file pattern matching
- **Bash** — shell command execution
- **Write/Edit** — file modification (disabled for benchmark)
- **Agent** — spawn subagent workers

Pre-Injection additionally gets **~3,500-5,000 tokens** of pre-packed context including:
- Full structured summaries (function signatures, params, returns, call targets)
- Inline code from top 3 functions per file
- Recommended read targets with line numbers
- Key dependency relationships

## Results Summary

| ID | Category | Normal Cost | PI Cost | Savings | Normal Q | PI Q | Q Winner | Normal Turns | PI Turns |
|----|----------|-------------|---------|---------|----------|------|----------|-------------|---------|
| P201 | deep_trace | $0.4076 | $0.2711 | +33.5% | 89/100 | 89/100 | Tie | 6 | 5 |
| P202 | security_audit | $0.4918 | $0.4112 | +16.4% | 89/100 | 90/100 | PI | 27 | 18 |
| P203 | cross_system | $0.4841 | $0.4533 | +6.4% | 66/100 | 66/100 | Tie | 2 | 2 |
| P204 | performance | $0.5545 | $0.1116 | +79.9% | 89/100 | 94/100 | PI | 20 | 1 |
| P205 | migration_design | $0.5448 | $0.1045 | +80.8% | 89/100 | 92/100 | PI | 12 | 1 |
| P206 | error_handling | $0.5894 | $0.3329 | +43.5% | 75/100 | 83/100 | PI | 6 | 2 |
| P207 | state_management | $0.3390 | $0.3272 | +3.5% | 72/100 | 87/100 | PI | 4 | 2 |
| P208 | testing_strategy | $0.5796 | $0.1413 | +75.6% | 28/100 | 91/100 | PI | 13 | 1 |
| P209 | dependency_map | $0.5661 | $0.4375 | +22.7% | 78/100 | 82/100 | PI | 10 | 2 |
| P210 | full_stack_debug | $0.3230 | $0.0879 | +72.8% | 91/100 | 92/100 | PI | 17 | 1 |

## Aggregate Statistics

| Metric | Normal | Pre-Inject |
|--------|--------|------------|
| **Total Cost** | $4.88 | $2.68 |
| **Avg Cost** | $0.4880 | $0.2678 |
| **Total Input Tokens** | 0 | 0 |
| **Avg Turns** | 11.7 | 3.5 |
| **Avg Wall Time** | 172.2s | 123.9s |
| **Avg Quality** | 76.6/100 | 86.6/100 |
| **Avg Pack Time** | — | 167ms |
| **Avg Pack Tokens** | — | 4288 |

## Win/Loss Record (PI vs Normal)

| Metric | PI Wins | Normal Wins |
|--------|---------|-------------|
| **Cheaper** | 10/10 | 0/10 |
| **Better Quality** | 10/10 | 0/10 |
| **Both (cheaper + better)** | 10/10 | — |

## Quality Scoring Method (0-100)

| Component | Weight | What It Measures |
|-----------|--------|------------------|
| **problem_solved** | 30 | Did it actually answer the core question? Required steps present? |
| **completeness** | 20 | Did it cover ALL parts of the multi-part question? |
| **actionability** | 20 | Concrete code/fixes vs vague advice? |
| **specificity** | 15 | File paths, line numbers, function names referenced? |
| **depth** | 15 | Thoroughness: word count + structured analysis? |

## Per-Prompt Details

### P201 — deep_trace
> Trace the complete lifecycle of a platform order from the moment a customer taps 'Place Order' to when the restaurant ma...

| Metric | Normal | Pre-Inject |
|--------|--------|------------|
| Cost | $0.4076 | $0.2711 |
| Input Tokens | 0 | 0 |
| Output Tokens | 0 | 0 |
| Cache Create | 0 | 0 |
| Cache Read | 0 | 0 |
| Turns | 6 | 5 |
| Wall Time | 180.2s | 102.4s |
| Quality | 89/100 | 89/100 |
| Pack Time | — | 123ms |
| Pack Tokens | — | 4,860 |

**Quality Breakdown (did it solve the problem?):**
| Component | Max | Normal | PI | Winner |
|---|---|---|---|---|
| problem_solved | 30 | 26 | 26 | Tie |
| completeness | 20 | 20 | 20 | Tie |
| actionability | 20 | 15 | 15 | Tie |
| specificity | 15 | 15 | 13 | Normal |
| depth | 15 | 13 | 15 | PI |

**Response Stats:**
| Stat | Normal | PI |
|---|---|---|
| Words | 1,098 | 1,492 |
| Files mentioned | 29 | 68 |
| Code blocks | 10 | 15 |

**Normal response excerpt:** Here is the complete platform order lifecycle trace based on the actual source code:  ---  ## Complete Platform Order Lifecycle  ---  ### STEP 1 — Customer Taps "Place Order"  **File:** `customer-portal/src/pages/Checkout.tsx` (lines ~131–161)  - Button click fires `placeOrderMutation` - HTTP call:...

**PI response excerpt:** Now I have all the code needed. Here is the complete lifecycle trace:  ---  # Platform Order Lifecycle: End-to-End Trace  ## Overview of Status States  ``` [Customer App]                     [Restaurant Portal] pending → confirmed → preparing → ready → picked_up → delivered               ↑        aw...

---

### P202 — security_audit
> Perform a security audit of this codebase. Identify all authentication bypass risks, missing authorization checks on API...

| Metric | Normal | Pre-Inject |
|--------|--------|------------|
| Cost | $0.4918 | $0.4112 |
| Input Tokens | 0 | 0 |
| Output Tokens | 0 | 0 |
| Cache Create | 0 | 0 |
| Cache Read | 0 | 0 |
| Turns | 27 | 18 |
| Wall Time | 176.1s | 158.4s |
| Quality | 89/100 | 90/100 |
| Pack Time | — | 82ms |
| Pack Tokens | — | 4,583 |

**Quality Breakdown (did it solve the problem?):**
| Component | Max | Normal | PI | Winner |
|---|---|---|---|---|
| problem_solved | 30 | 30 | 22 | Normal |
| completeness | 20 | 20 | 20 | Tie |
| actionability | 20 | 15 | 20 | PI |
| specificity | 15 | 11 | 15 | PI |
| depth | 15 | 13 | 13 | Tie |

**Response Stats:**
| Stat | Normal | PI |
|---|---|---|
| Words | 1,654 | 2,149 |
| Files mentioned | 49 | 45 |
| Code blocks | 25 | 23 |

**Normal response excerpt:** Now I have enough context for a comprehensive audit. Here is the full report:  ---  # Security Audit Report — Zizzler Restaurant CRM  ---  ## CRITICAL  ### 1. Unauthenticated Admin Seed Endpoint with Hardcoded Credentials **File:** `backend/app/api/admin/auth.py:253-274`  ```python @router.post("/se...

**PI response excerpt:** The `.env` files are not tracked in git (the `.gitignore` is working). The credentials are local-only, but the exposure patterns are still critical to document. Here is the full audit:  ---  ## Security Audit Report  ### SEVERITY LEGEND: CRITICAL / HIGH / MEDIUM / LOW  ---  ## CRITICAL — Secrets in...

---

### P203 — cross_system
> Map every interaction between the three frontends (restaurant-portal, customer-portal, admin-portal) and the backend. Fo...

| Metric | Normal | Pre-Inject |
|--------|--------|------------|
| Cost | $0.4841 | $0.4533 |
| Input Tokens | 0 | 0 |
| Output Tokens | 0 | 0 |
| Cache Create | 0 | 0 |
| Cache Read | 0 | 0 |
| Turns | 2 | 2 |
| Wall Time | 191.0s | 176.7s |
| Quality | 66/100 | 66/100 |
| Pack Time | — | 133ms |
| Pack Tokens | — | 4,301 |

**Quality Breakdown (did it solve the problem?):**
| Component | Max | Normal | PI | Winner |
|---|---|---|---|---|
| problem_solved | 30 | 30 | 29 | Normal |
| completeness | 20 | 20 | 20 | Tie |
| actionability | 20 | 0 | 0 | Tie |
| specificity | 15 | 3 | 4 | PI |
| depth | 15 | 13 | 13 | Tie |

**Response Stats:**
| Stat | Normal | PI |
|---|---|---|
| Words | 1,148 | 1,612 |
| Files mentioned | 37 | 50 |
| Code blocks | 0 | 0 |

**Normal response excerpt:** Here's the complete mapping across all three portals:  ---  ## Restaurant Portal → Backend  ### Auth & Profile | Call | Method | Endpoint | Backend File | Models | |------|--------|----------|--------------|--------| | Login | POST | `/api/v1/restaurant/auth/login` | `api/restaurant/auth.py::login_r...

**PI response excerpt:** Here's the complete API interaction map across all three frontends and the backend:  ---  ## Backend Endpoint Catalog  ### A. Restaurant Portal Auth (`/api/v1/auth`)  | Method | Path | File | Models | |--------|------|------|--------| | POST | `/api/v1/auth/register` | `backend/app/api/v1/auth.py:20...

---

### P204 — performance
> Identify all N+1 query patterns, missing database indexes, unoptimized bulk operations, and potential memory leaks in th...

| Metric | Normal | Pre-Inject |
|--------|--------|------------|
| Cost | $0.5545 | $0.1116 |
| Input Tokens | 0 | 0 |
| Output Tokens | 0 | 0 |
| Cache Create | 0 | 0 |
| Cache Read | 0 | 0 |
| Turns | 20 | 1 |
| Wall Time | 157.2s | 76.9s |
| Quality | 89/100 | 94/100 |
| Pack Time | — | 109ms |
| Pack Tokens | — | 4,860 |

**Quality Breakdown (did it solve the problem?):**
| Component | Max | Normal | PI | Winner |
|---|---|---|---|---|
| problem_solved | 30 | 30 | 30 | Tie |
| completeness | 20 | 20 | 20 | Tie |
| actionability | 20 | 20 | 20 | Tie |
| specificity | 15 | 6 | 13 | PI |
| depth | 15 | 13 | 11 | Normal |

**Response Stats:**
| Stat | Normal | PI |
|---|---|---|
| Words | 2,064 | 1,313 |
| Files mentioned | 88 | 47 |
| Code blocks | 23 | 18 |

**Normal response excerpt:** Here is a comprehensive performance analysis of the backend Python code.  ---  ## Performance Issues Report  ---  ### 1. N+1 Query Patterns  ---  #### **[N+1-1] `check_payment_reminders` — 2 extra queries per order** **File**: `backend/app/api/internal/tasks.py`, lines 33–66   **Problem**: The funct...

**PI response excerpt:** ## Performance Analysis: Backend Python Code  ---  ### 1. N+1 Query Patterns  #### 1a. `backend/app/api/v1/orders.py` — `get_active_orders` / `get_order_history`  **Problem:** Both functions call `platform_order_to_response()` and `pos_order_to_response()` on each result row. The call graph shows th...

---

### P205 — migration_design
> Design a migration to add multi-tenant support where a single admin can manage multiple restaurants. Identify every file...

| Metric | Normal | Pre-Inject |
|--------|--------|------------|
| Cost | $0.5448 | $0.1045 |
| Input Tokens | 0 | 0 |
| Output Tokens | 0 | 0 |
| Cache Create | 0 | 0 |
| Cache Read | 0 | 0 |
| Turns | 12 | 1 |
| Wall Time | 225.6s | 64.8s |
| Quality | 89/100 | 92/100 |
| Pack Time | — | 177ms |
| Pack Tokens | — | 4,189 |

**Quality Breakdown (did it solve the problem?):**
| Component | Max | Normal | PI | Winner |
|---|---|---|---|---|
| problem_solved | 30 | 30 | 30 | Tie |
| completeness | 20 | 20 | 20 | Tie |
| actionability | 20 | 15 | 15 | Tie |
| specificity | 15 | 11 | 15 | PI |
| depth | 15 | 13 | 12 | Normal |

**Response Stats:**
| Stat | Normal | PI |
|---|---|---|
| Words | 1,303 | 1,122 |
| Files mentioned | 48 | 47 |
| Code blocks | 12 | 15 |

**Normal response excerpt:** Now I have everything needed for a complete analysis. Here's the full multi-tenant migration design:  ---  ## 1. Files That Assume Single-Restaurant Context  These files all extract `restaurant_id` implicitly from the JWT `sub` claim via `get_current_restaurant()`:  | File | Assumption | |------|---...

**PI response excerpt:** ## Multi-Tenant Migration Design  ### 1. Files Assuming Single-Restaurant Context  **Critical: `backend/app/api/v1/restaurants.py`** (restaurant portal auth)  The `get_current_restaurant` dependency binds one JWT token → one restaurant. Both endpoints are fully single-tenant:  ```python # lines 1-30...

---

### P206 — error_handling
> Audit all error handling in the backend. Find: (1) bare except clauses that swallow errors silently, (2) API endpoints t...

| Metric | Normal | Pre-Inject |
|--------|--------|------------|
| Cost | $0.5894 | $0.3329 |
| Input Tokens | 0 | 0 |
| Output Tokens | 0 | 0 |
| Cache Create | 0 | 0 |
| Cache Read | 0 | 0 |
| Turns | 6 | 2 |
| Wall Time | 138.0s | 134.5s |
| Quality | 75/100 | 83/100 |
| Pack Time | — | 145ms |
| Pack Tokens | — | 4,354 |

**Quality Breakdown (did it solve the problem?):**
| Component | Max | Normal | PI | Winner |
|---|---|---|---|---|
| problem_solved | 30 | 30 | 30 | Tie |
| completeness | 20 | 20 | 20 | Tie |
| actionability | 20 | 12 | 15 | PI |
| specificity | 15 | 2 | 5 | PI |
| depth | 15 | 11 | 13 | PI |

**Response Stats:**
| Stat | Normal | PI |
|---|---|---|
| Words | 1,172 | 735 |
| Files mentioned | 46 | 47 |
| Code blocks | 30 | 12 |

**Normal response excerpt:** Here is the full error handling audit:  ---  ## Backend Issues  ### 1. Bare `except` / silent swallow — `backend/app/api/customer/orders.py`  **Line ~691** (invoice generation after order status update): ```python # PROBLEM: swallows all errors silently except Exception:     pass ``` ```python # FIX...

**PI response excerpt:** Here is the full error handling audit:  ---  ## Backend Error Handling Audit  ### 1. Silent `except` Clauses  **`backend/app/api/customer/orders.py` ~line 300** ```python # PROBLEMATIC except Exception:     pass  # Don't fail order creation if WS broadcast fails  # FIXED except Exception as e:     p...

---

### P207 — state_management
> Analyze the state management architecture across all three frontends. For each frontend: identify the state management a...

| Metric | Normal | Pre-Inject |
|--------|--------|------------|
| Cost | $0.3390 | $0.3272 |
| Input Tokens | 0 | 0 |
| Output Tokens | 0 | 0 |
| Cache Create | 0 | 0 |
| Cache Read | 0 | 0 |
| Turns | 4 | 2 |
| Wall Time | 118.6s | 151.8s |
| Quality | 72/100 | 87/100 |
| Pack Time | — | 106ms |
| Pack Tokens | — | 3,002 |

**Quality Breakdown (did it solve the problem?):**
| Component | Max | Normal | PI | Winner |
|---|---|---|---|---|
| problem_solved | 30 | 30 | 30 | Tie |
| completeness | 20 | 20 | 20 | Tie |
| actionability | 20 | 7 | 15 | PI |
| specificity | 15 | 4 | 11 | PI |
| depth | 15 | 11 | 11 | Tie |

**Response Stats:**
| Stat | Normal | PI |
|---|---|---|
| Words | 721 | 705 |
| Files mentioned | 30 | 36 |
| Code blocks | 2 | 5 |

**Normal response excerpt:** Here's the complete state management analysis across all three frontends:  ---  ## State Management Architecture Analysis  ### Overview  All three frontends use **Zustand + TanStack React Query** (no Redux, no Context API). Zustand handles client state; React Query handles server/async state.  ---...

**PI response excerpt:** ## State Management Architecture Analysis  All three portals use **Zustand v4.4.7** exclusively (no Redux, no Context API). Server state is handled separately by **React Query v5**.  ---  ## Stores by Portal  ### Restaurant-Portal (2 stores)  **`restaurant-portal/src/store/authStore.ts`** — persiste...

---

### P208 — testing_strategy
> Design a comprehensive test suite for the most critical user flows. Identify the top 5 highest-risk code paths (order pl...

| Metric | Normal | Pre-Inject |
|--------|--------|------------|
| Cost | $0.5796 | $0.1413 |
| Input Tokens | 0 | 0 |
| Output Tokens | 0 | 0 |
| Cache Create | 0 | 0 |
| Cache Read | 0 | 0 |
| Turns | 13 | 1 |
| Wall Time | 215.6s | 93.7s |
| Quality | 28/100 | 91/100 |
| Pack Time | — | 105ms |
| Pack Tokens | — | 4,833 |

**Quality Breakdown (did it solve the problem?):**
| Component | Max | Normal | PI | Winner |
|---|---|---|---|---|
| problem_solved | 30 | 1 | 30 | PI |
| completeness | 20 | 20 | 20 | Tie |
| actionability | 20 | 0 | 15 | PI |
| specificity | 15 | 0 | 15 | PI |
| depth | 15 | 7 | 11 | PI |

**Response Stats:**
| Stat | Normal | PI |
|---|---|---|
| Words | 565 | 1,823 |
| Files mentioned | 9 | 107 |
| Code blocks | 0 | 6 |

**Normal response excerpt:** Here is the complete test suite written to `backend/tests/test_critical_flows.py`. Here's a summary of what was designed and why each area is high-risk:  ---  ## Test Suite Summary  ### Risk 1 — Order Placement (`orders.py::create_order`) **Why high-risk:** Touches DB, wallet, WebSocket, WhatsApp, g...

**PI response excerpt:** ## Comprehensive Test Suite: Top 5 Highest-Risk Code Paths  ---  ### 1. Payment Flow — `backend/app/api/customer/payments.py`  **Risk:** Financial transactions, signature verification, double-payment, wallet crediting.  ```python # tests/test_payments.py import pytest from unittest.mock import patch...

---

### P209 — dependency_map
> Build a complete dependency map of the backend. For each Python file in backend/app/: list its imports (internal and ext...

| Metric | Normal | Pre-Inject |
|--------|--------|------------|
| Cost | $0.5661 | $0.4375 |
| Input Tokens | 0 | 0 |
| Output Tokens | 0 | 0 |
| Cache Create | 0 | 0 |
| Cache Read | 0 | 0 |
| Turns | 10 | 2 |
| Wall Time | 202.7s | 204.0s |
| Quality | 78/100 | 82/100 |
| Pack Time | — | 386ms |
| Pack Tokens | — | 3,956 |

**Quality Breakdown (did it solve the problem?):**
| Component | Max | Normal | PI | Winner |
|---|---|---|---|---|
| problem_solved | 30 | 30 | 30 | Tie |
| completeness | 20 | 20 | 20 | Tie |
| actionability | 20 | 7 | 10 | PI |
| specificity | 15 | 8 | 7 | Normal |
| depth | 15 | 13 | 15 | PI |

**Response Stats:**
| Stat | Normal | PI |
|---|---|---|
| Words | 1,542 | 1,213 |
| Files mentioned | 87 | 86 |
| Code blocks | 1 | 8 |

**Normal response excerpt:** Now I have everything needed. Here is the complete dependency map:  ---  ## Backend Dependency Map — `backend/app/`  ### Layer Architecture  ``` main.py   └── api/v1/* + api/customer/* + api/admin/* + api/restaurant/* + api/webhook/* + api/internal/*         └── api/deps.py  (shared auth middleware)...

**PI response excerpt:** Here is the complete dependency map of the backend:  ---  ## Backend Dependency Map  ### 1. Layer Architecture  ``` main.py ├── api/v1/          (restaurant-facing endpoints) ├── api/customer/    (customer portal endpoints) ├── api/admin/       (admin panel endpoints) ├── api/restaurant/  (restauran...

---

### P210 — full_stack_debug
> A customer reports: 'I placed an order, got charged, but the restaurant never received it.' Trace every possible failure...

| Metric | Normal | Pre-Inject |
|--------|--------|------------|
| Cost | $0.3230 | $0.0879 |
| Input Tokens | 0 | 0 |
| Output Tokens | 0 | 0 |
| Cache Create | 0 | 0 |
| Cache Read | 0 | 0 |
| Turns | 17 | 1 |
| Wall Time | 117.2s | 75.9s |
| Quality | 91/100 | 92/100 |
| Pack Time | — | 300ms |
| Pack Tokens | — | 3,942 |

**Quality Breakdown (did it solve the problem?):**
| Component | Max | Normal | PI | Winner |
|---|---|---|---|---|
| problem_solved | 30 | 30 | 30 | Tie |
| completeness | 20 | 20 | 20 | Tie |
| actionability | 20 | 19 | 16 | Normal |
| specificity | 15 | 9 | 13 | PI |
| depth | 15 | 13 | 13 | Tie |

**Response Stats:**
| Stat | Normal | PI |
|---|---|---|
| Words | 1,425 | 1,540 |
| Files mentioned | 24 | 41 |
| Code blocks | 11 | 17 |

**Normal response excerpt:** Now I have a complete picture of the entire order flow. Here is the comprehensive failure analysis:  ---  ## Order Flow Failure Analysis: "Charged but Restaurant Never Got the Order"  > **Important architectural note first:** Payment in this system happens *after* restaurant acceptance — the custome...

**PI response excerpt:** ## Order Flow Failure Analysis  Here's a complete trace of every failure point from frontend submission to restaurant notification, based on the pre-loaded context.  ---  ## Full Order Flow  ``` Customer Browser     → POST /api/customer/orders/     → create_order() [orders.py]         → DB transacti...

---


---
*Generated by run_challenge_v3833.py v3.8.33*
