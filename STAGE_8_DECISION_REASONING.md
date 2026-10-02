# STAGE 8 — DECISION & REASONING AGENT

**Project Title:** AI Loan Underwriting Assistant: A Multi-Agent Agentic AI System for Faster Loan Processing  
**Stage:** Stage 8 — Decision & Reasoning Agent  
**Status:** COMPLETE (Stage 9 Dashboard & Audit Trail NOT started)  
**Governance Model:** Human-in-the-Loop Decision Support  

---

> [!IMPORTANT]
> **GOVERNANCE & RESPONSIBLE AI NOTICE:**  
> The system generates an explainable AI recommendation for academic research and software testing. It does not constitute a final banking decision, and an authorized human remains responsible for the final decision.  
> The synthetic dataset does not represent real-world default outcomes or real-world fraud prevalence.

---

## 1. Primary Objective

The primary objective of Stage 8 is to implement a deterministic, transparent, and auditable **Decision & Reasoning Agent** (`DecisionReasoningAgent`) that synthesizes the multi-agent analytical outputs collected by the Stage 7 Multi-Agent Orchestrator into one of three public categorical recommendations:

```text
APPROVE
REJECT
MANUAL_REVIEW
```

The decision engine operates under strict design constraints:
- **Zero LLMs / External Cloud APIs**: Operates 100% locally using deterministic policy rules and formal reasoning algorithms. No calls to OpenAI, Gemini, Anthropic, LangChain, CrewAI, or AutoGen.
- **No Machine Learning Model Retraining**: Does not train a new ML classifier or modify the Stage 5 Random Forest risk model.
- **Strict Evidence Backing & Auditability**: Every recommendation is linked to traceable reason codes, positive/negative/blocking factors, extracted document citations, and an evidence completeness confidence score.
- **Human-in-the-Loop (HITL)**: All generated recommendations flag `human_review_required = True`. The engine acts as an underwriting decision-support tool, not an autonomous, irreversible banking system.

---

## 2. Input Specification

The Decision & Reasoning Agent consumes the unified Stage 7 `UnderwritingAnalysisResult` data contract (or individual agent findings):

```text
Stage 7: UnderwritingAnalysisResult
  ├── application_id: str
  ├── orchestration_status: OrchestrationStatus (SUCCESS, PARTIAL_SUCCESS, FAILED)
  ├── agent_statuses: Dict[str, AgentExecutionStatus]
  ├── document_result: DocumentPackageResult (Stage 3)
  ├── eligibility_result: EligibilityResult (Stage 4)
  ├── risk_result: RiskResult (Stage 5)
  └── anomaly_result: AnomalyResult (Stage 6)
                      │
                      ▼
         [Decision & Reasoning Agent]
                      │
                      ▼
         Stage 8: DecisionReasoningResult
           ├── recommendation: DecisionOutcome (APPROVE | REJECT | MANUAL_REVIEW)
           ├── confidence: float (0.0 – 100.0%)
           ├── human_review_required: bool (True)
           ├── reasons: List[DecisionReason]
           ├── positive_factors: List[str]
           ├── negative_factors: List[str]
           ├── blocking_factors: List[str]
           ├── supporting_evidence: List[Dict[str, Any]]
           ├── summary: str
           ├── policy_version: str ("decision_policy_v1")
           └── reasoning_version: str ("reasoning_v1")
```

The agent does **not** independently re-execute Stage 3, Stage 4, Stage 5, or Stage 6. It consumes their verified outputs directly.

---

## 3. Centralized Decision Policy

All underwriting thresholds, policy actions, and governance parameters are centralized in `app/decision/policy.py` under `DecisionPolicy`:

```python
class DecisionPolicy(BaseModel):
    policy_version: str = "decision_policy_v1"
    permitted_approval_risk_tiers: List[RiskLevel] = [RiskLevel.LOW, RiskLevel.MEDIUM]
    borderline_risk_action: DecisionOutcome = DecisionOutcome.MANUAL_REVIEW
    high_risk_action: DecisionOutcome = DecisionOutcome.REJECT
    min_confidence_for_approval: float = 70.0
    tolerated_anomaly_severities_for_approval: Set[AnomalySeverity] = {
        AnomalySeverity.NONE,
        AnomalySeverity.LOW,
    }
    blocking_anomaly_severities: Set[AnomalySeverity] = {
        AnomalySeverity.HIGH,
        AnomalySeverity.MEDIUM,
    }
    mandatory_eligibility_status_for_approval: EligibilityStatus = EligibilityStatus.ELIGIBLE
    enforce_complete_documents: bool = True
```

Decision thresholds are never scattered across multiple files or hardcoded into applicant-specific conditional branches.

---

## 4. Rule Precedence Hierarchy

The decision engine evaluates multi-agent evidence according to a strict, documented 7-tier priority precedence:

```text
┌────────────────────────────────────────────────────────┐
│ Priority 1: Pipeline Integrity Check                   │
│ (FAILED Pipeline → MANUAL_REVIEW)                      │
└──────────────────────────┬─────────────────────────────┘
                           ▼
┌────────────────────────────────────────────────────────┐
│ Priority 2: Critical Eligibility Failure Check         │
│ (INELIGIBLE Status → REJECT)                           │
└──────────────────────────┬─────────────────────────────┘
                           ▼
┌────────────────────────────────────────────────────────┐
│ Priority 3: Mandatory Evidence Completeness Check      │
│ (Missing Required Documents → MANUAL_REVIEW)           │
└──────────────────────────┬─────────────────────────────┘
                           ▼
┌────────────────────────────────────────────────────────┐
│ Priority 4: Material Cross-Document Discrepancy Check  │
│ (HIGH / MEDIUM Anomaly Severity → MANUAL_REVIEW)       │
└──────────────────────────┬─────────────────────────────┘
                           ▼
┌────────────────────────────────────────────────────────┐
│ Priority 5: Eligibility Review Required Check          │
│ (REVIEW_REQUIRED Status → MANUAL_REVIEW)               │
└──────────────────────────┬─────────────────────────────┘
                           ▼
┌────────────────────────────────────────────────────────┐
│ Priority 6: Repayment Risk Assessment Check            │
│ (HIGH Risk → REJECT; BORDERLINE Risk → MANUAL_REVIEW)  │
└──────────────────────────┬─────────────────────────────┘
                           ▼
┌────────────────────────────────────────────────────────┐
│ Priority 7: Clean Approval Synthesis                   │
│ (Eligible + Acceptable Risk + Complete Docs → APPROVE) │
└────────────────────────────────────────────────────────┘
```

### Detailed Precedence Rules:
1. **Priority 1 — Pipeline Integrity**: If the multi-agent pipeline failed (`OrchestrationStatus.FAILED`), the system routes the application to `MANUAL_REVIEW`. It does not reject an applicant due to internal infrastructure failure.
2. **Priority 2 — Critical Eligibility Failure**: If Stage 4 returns `INELIGIBLE` due to hard policy failures (e.g., credit score < 650, age out of bounds), the decision engine immediately issues a deterministic `REJECT`.
3. **Priority 3 — Critical Missing Evidence**: If required verification documents are missing (e.g., absent bank statement), the engine routes to `MANUAL_REVIEW`. Missing evidence is **never** equated to confirmed fraud.
4. **Priority 4 — Material Cross-Document Discrepancies**: If Stage 6 reports `HIGH` or `MEDIUM` severity inconsistencies (e.g., salary slip vs. bank deposit discrepancy, name mismatch), the application is routed to `MANUAL_REVIEW` for human verification.
5. **Priority 5 — Eligibility Review Required**: If Stage 4 returns `REVIEW_REQUIRED`, the application is routed to `MANUAL_REVIEW`.
6. **Priority 6 — Borderline Risk Profile**: If Stage 5 classifies credit risk as `BORDERLINE`, human judgment is required (`MANUAL_REVIEW`). If assessed as `HIGH`, it is rejected under configured risk policy (`REJECT`).
7. **Priority 7 — Acceptable Application**: If eligibility is `ELIGIBLE`, risk is `LOW` or `MEDIUM`, no severe anomalies exist, and evidence is complete, the engine issues an `APPROVE` recommendation.

---

## 5. Combinatorial Decision Matrix

The following decision matrix formalizes the core combinatorial interactions between analytical agents:

| Eligibility Status | Risk Tier | Anomaly Severity | Missing Evidence | Recommendation | Primary Rule Applied |
|---|---|---|---|---|---|
| `ELIGIBLE` | `LOW` | `NONE` | No | **`APPROVE`** | Acceptable policy profile (Priority 7) |
| `ELIGIBLE` | `MEDIUM` | `NONE` | No | **`APPROVE`** | Acceptable policy profile (Priority 7) |
| `ELIGIBLE` | `BORDERLINE` | `NONE` | No | **`MANUAL_REVIEW`** | Borderline repayment uncertainty (Priority 6) |
| `ELIGIBLE` | `HIGH` | `NONE` | No | **`REJECT`** | Risk exceeds lending tolerance (Priority 6) |
| `ELIGIBLE` | `LOW` | `HIGH` | No | **`MANUAL_REVIEW`** | Unresolved cross-document anomaly (Priority 4) |
| `ELIGIBLE` | `MEDIUM` | `MEDIUM` | No | **`MANUAL_REVIEW`** | Discrepancy requiring review (Priority 4) |
| `REVIEW_REQUIRED` | `LOW` | `NONE` | No | **`MANUAL_REVIEW`** | Policy review required (Priority 5) |
| `INELIGIBLE` | `LOW` | `NONE` | No | **`REJECT`** | Hard eligibility rule failed (Priority 2) |
| `INELIGIBLE` | `HIGH` | `HIGH` | No | **`REJECT`** | Hard eligibility rule failed (Priority 2) |
| `ELIGIBLE` | `LOW` | `NONE` | Yes (`bank_statement`) | **`MANUAL_REVIEW`** | Incomplete documentation (Priority 3) |
| Any | Any | Any | N/A (`Pipeline FAILED`) | **`MANUAL_REVIEW`** | System infrastructure failure (Priority 1) |

---

## 6. Decision Reason Codes

Every decision includes standardized, machine-readable reason codes indexed in `app/decision/policy.py`:

| Reason Code | Domain Category | Impact Severity | Description |
|---|---|---|---|
| `DEC-SYS-001` | `SYSTEM` | `BLOCKING` | Pipeline execution failed; manual technical and underwriting review required. |
| `DEC-SYS-002` | `SYSTEM` | `WARNING` | Pipeline finished with partial success; one or more analytical agents failed. |
| `DEC-DOC-001` | `DOCUMENT` | `BLOCKING` | Mandatory document evidence is missing; complete verification cannot proceed. |
| `DEC-DOC-002` | `DOCUMENT` | `INFO` | All required application and supporting documents are verified and present. |
| `DEC-ELIG-001` | `ELIGIBILITY` | `BLOCKING` | Applicant is INELIGIBLE due to failure of mandatory underwriting policy rules. |
| `DEC-ELIG-002` | `ELIGIBILITY` | `WARNING` | Underwriting eligibility requires manual review under configured policy. |
| `DEC-ELIG-003` | `ELIGIBILITY` | `INFO` | All underwriting eligibility criteria are satisfied. |
| `DEC-RISK-001` | `RISK` | `WARNING` | Assessed credit risk is BORDERLINE; requires human credit underwriter review. |
| `DEC-RISK-002` | `RISK` | `BLOCKING` | Assessed credit risk profile is HIGH, exceeding acceptable lending tolerance. |
| `DEC-RISK-003` | `RISK` | `INFO` | Assessed repayment risk profile is within acceptable policy limits. |
| `DEC-ANOM-001` | `ANOMALY` | `BLOCKING` | High-severity cross-document identity or evidence inconsistency detected. |
| `DEC-ANOM-002` | `ANOMALY` | `WARNING` | Material cross-document discrepancy detected; human verification required. |
| `DEC-ANOM-003` | `ANOMALY` | `INFO` | No suspicious cross-document anomalies or discrepancies detected. |
| `DEC-APP-001` | `SYNTHESIS` | `INFO` | Application satisfies all eligibility, risk, consistency, and documentation criteria. |

---

## 7. Decision Confidence Methodology

The Decision Confidence Score ($C \in [0.0, 100.0]$) quantifies **evidence completeness and analytical agreement**.

> [!CAUTION]
> **STATISTICAL NOTICE:**  
> The Decision Confidence score is **NOT** a probability of loan default, repayment, or fraud. It reflects internal pipeline consistency and completeness of evidence.

### Formula & Deduction Schedule:
The score starts at $100.0\%$ and undergoes deterministic deductions based on missing evidence and analytical friction:

$$C = \max(10.0, 100.0 - D_{\text{system}} - D_{\text{docs}} - D_{\text{risk}} - D_{\text{anomaly}})$$

- **System Deductions ($D_{\text{system}}$)**:
  - Pipeline `FAILED`: $-60.0\%$
  - Pipeline `PARTIAL_SUCCESS`: $-25.0\%$
- **Document Deductions ($D_{\text{docs}}$)**:
  - Missing mandatory documents: $-20.0\%$ (base) $- 5.0\%$ per additional missing document
- **Risk Deductions ($D_{\text{risk}}$)**:
  - `BORDERLINE` risk tier: $-15.0\%$
- **Anomaly Deductions ($D_{\text{anomaly}}$)**:
  - `HIGH` severity anomaly: $-25.0\%$
  - `MEDIUM` severity anomaly: $-15.0\%$
  - `LOW` severity anomaly: $-5.0\%$

---

## 8. Evidence Traceability & Factor Categorization

The Decision Agent extracts and categorizes granular findings into transparent structured fields:

1. **`positive_factors`**: Key credit-positive attributes and protective factors (e.g., "4 mandatory supporting document(s) verified", "All underwriting eligibility criteria satisfied", "Protective: Credit history established").
2. **`negative_factors`**: Identified adverse debt burdens, borderline thresholds, or cross-document discrepancies.
3. **`blocking_factors`**: Critical policy failures or verification hurdles preventing automated approval (e.g., "Ineligible under policy rules: MIN_CREDIT_SCORE", "Missing mandatory document(s): bank_statement").
4. **`supporting_evidence`**: Structured citations tracing originating agent, rule name, expected value, observed value, and document filenames.

---

## 9. Human-in-the-Loop (HITL) Design

To ensure compliance with banking ethics and regulatory standards:
1. **Advisory Posture**: The system produces an **AI Recommendation**, not an automated banking decision.
2. **Mandatory Human Authority**: Every `DecisionReasoningResult` enforces `human_review_required = True`.
3. **Executive Narrative**: A natural-language explanation summarizes primary drivers, outstanding verification items, and governance notices.
4. **Standard Governance Notice**:
   > *"This automated decision-support recommendation does not constitute a final credit commitment. Final lending authority rests with authorized human underwriters."*

---

## 10. Synthetic Cohort Evaluation (APP0001–APP0030)

Stage 8 was evaluated across all 30 controlled synthetic applicant packages using `scripts/evaluate_decisions.py`:

```text
================================================================================
    STAGE 8 — DECISION & REASONING AGENT UNDERWRITING EVALUATION REPORT
================================================================================
Total Evaluated Applications: 30
Decision Policy Version:      decision_policy_v1
Architecture:                 Deterministic Multi-Agent Evidence Synthesis
Governance Notice:            AI recommendation only; human underwriter holds final authority
--------------------------------------------------------------------------------

[PART 1: PER-APPLICANT UNDERWRITING DECISION LEDGER]
--------------------------------------------------------------------------------
App ID    Eligibility  Risk Tier    Anomaly    Recommendation  Conf (%)   Primary Reason Code
--------------------------------------------------------------------------------
APP0001   INELIGIBLE   HIGH         NONE       REJECT          100.0      DEC-ELIG-001
APP0002   ELIGIBLE     MEDIUM       NONE       APPROVE         100.0      DEC-APP-001
APP0003   ELIGIBLE     LOW          NONE       APPROVE         100.0      DEC-APP-001
APP0004   ELIGIBLE     MEDIUM       NONE       APPROVE         100.0      DEC-APP-001
APP0005   ELIGIBLE     MEDIUM       NONE       APPROVE         100.0      DEC-APP-001
APP0006   ELIGIBLE     LOW          MEDIUM     MANUAL_REVIEW   85.0       DEC-ANOM-001
APP0007   ELIGIBLE     LOW          MEDIUM     MANUAL_REVIEW   85.0       DEC-ANOM-001
APP0008   ELIGIBLE     BORDERLINE   MEDIUM     MANUAL_REVIEW   70.0       DEC-ANOM-001
APP0009   ELIGIBLE     LOW          MEDIUM     MANUAL_REVIEW   85.0       DEC-ANOM-001
APP0010   ELIGIBLE     MEDIUM       MEDIUM     MANUAL_REVIEW   85.0       DEC-ANOM-001
APP0011   ELIGIBLE     LOW          MEDIUM     MANUAL_REVIEW   85.0       DEC-ANOM-001
APP0012   INELIGIBLE   HIGH         MEDIUM     REJECT          85.0       DEC-ELIG-001
APP0013   ELIGIBLE     MEDIUM       MEDIUM     MANUAL_REVIEW   85.0       DEC-ANOM-001
APP0014   INELIGIBLE   HIGH         MEDIUM     REJECT          85.0       DEC-ELIG-001
APP0015   ELIGIBLE     MEDIUM       MEDIUM     MANUAL_REVIEW   85.0       DEC-ANOM-001
APP0016   REVIEW_REQ   BORDERLINE   NONE       MANUAL_REVIEW   60.0       DEC-DOC-001
APP0017   REVIEW_REQ   MEDIUM       NONE       MANUAL_REVIEW   75.0       DEC-DOC-001
APP0018   INELIGIBLE   BORDERLINE   NONE       REJECT          75.0       DEC-ELIG-001
APP0019   REVIEW_REQ   LOW          NONE       MANUAL_REVIEW   75.0       DEC-DOC-001
APP0020   REVIEW_REQ   MEDIUM       NONE       MANUAL_REVIEW   75.0       DEC-DOC-001
APP0021   INELIGIBLE   HIGH         MEDIUM     REJECT          85.0       DEC-ELIG-001
APP0022   ELIGIBLE     LOW          MEDIUM     MANUAL_REVIEW   85.0       DEC-ANOM-001
APP0023   INELIGIBLE   BORDERLINE   MEDIUM     REJECT          70.0       DEC-ELIG-001
APP0024   ELIGIBLE     BORDERLINE   MEDIUM     MANUAL_REVIEW   70.0       DEC-ANOM-001
APP0025   INELIGIBLE   BORDERLINE   MEDIUM     REJECT          70.0       DEC-ELIG-001
APP0026   ELIGIBLE     BORDERLINE   NONE       MANUAL_REVIEW   85.0       DEC-RISK-001
APP0027   ELIGIBLE     BORDERLINE   NONE       MANUAL_REVIEW   85.0       DEC-RISK-001
APP0028   ELIGIBLE     BORDERLINE   NONE       MANUAL_REVIEW   85.0       DEC-RISK-001
APP0029   INELIGIBLE   BORDERLINE   NONE       REJECT          85.0       DEC-ELIG-001
APP0030   ELIGIBLE     BORDERLINE   NONE       MANUAL_REVIEW   85.0       DEC-RISK-001
--------------------------------------------------------------------------------
```

---

## 11. Aggregate Decision Distribution & Research Metrics

Across the 30 evaluation packages:

### Decision Distribution:
- **`APPROVE`**: 4 applications (13.3%)
- **`REJECT`**: 8 applications (26.7%)
- **`MANUAL_REVIEW`**: 18 applications (60.0%)

$$\text{Manual Review Rate} = \frac{18}{30} = 60.0\%$$

### Reason Code Distribution:
- `DEC-ANOM-001` (Cross-document discrepancy detected): 10 occurrences
- `DEC-ELIG-001` (Mandatory underwriting rule failed / INELIGIBLE): 8 occurrences
- `DEC-RISK-002` (High credit risk profile): 4 occurrences
- `DEC-APP-001` (All policy requirements satisfied): 4 occurrences
- `DEC-DOC-001` (Mandatory document evidence missing): 4 occurrences
- `DEC-RISK-001` (Borderline credit risk profile): 4 occurrences

### Evidence Completeness Audit:
- **Complete verified documentation**: 25 / 30 (83.3%)
- **Incomplete / Missing evidence**: 5 / 30 (16.7%) (`APP0016`–`APP0020`)
- **Partial pipeline executions**: 0 / 30 (0.0%)

### Cohort Breakdown:
- **Normal / Document-Consistent (`APP0001`–`APP0005`)**: 4 APPROVE, 1 REJECT (`APP0001` has credit score 612 < 650).
- **Income Mismatch (`APP0006`–`APP0010`)**: 5 MANUAL_REVIEW (Discrepancy routed to human verification).
- **Name Mismatch (`APP0011`–`APP0015`)**: 3 MANUAL_REVIEW, 2 REJECT (`APP0012`, `APP0014` failed minimum credit score).
- **Missing Documents (`APP0016`–`APP0020`)**: 4 MANUAL_REVIEW, 1 REJECT (`APP0018` failed minimum credit score).
- **Financial Inconsistency (`APP0021`–`APP0025`)**: 2 MANUAL_REVIEW, 3 REJECT (`APP0021`, `APP0023`, `APP0025` failed minimum credit score).
- **Borderline Risk (`APP0026`–`APP0030`)**: 4 MANUAL_REVIEW, 1 REJECT (`APP0029` failed minimum credit score).

---

## 12. Methodological & Analytical Limitations

1. **Synthetic Dataset**: All 30 document packages were generated using controlled templates and synthetic applicant profiles. The results demonstrate policy mechanics and multi-agent coordination rather than empirical loan default rates or banking fraud prevalence.
2. **Deterministic Heuristic Confidence**: The confidence score measures pipeline completeness and agent agreement. It is not an empirical Bayesian posterior probability of default or repayment.
3. **No Legal Authority**: The prototype recommendation does not constitute legal or banking approval.

---

## 13. Ethical Considerations

1. **Distinction Between Anomaly and Fraud**: An anomaly is a mathematical or textual inconsistency between documents. It may arise from data entry typos, nickname usage, or employer reporting lags. The Decision Agent never accuses an applicant of fraud; it requests human review.
2. **Separation of Risk and Eligibility**: Risk models predict continuous scores, whereas eligibility represents binary compliance with underwriting policies. They are reasoned about separately.
3. **Fair Lending & Anti-Bias**: Decisions are strictly rule-based, deterministic, and auditable. Demographic proxies and unverified black-box signals are prohibited.

---

## 14. Stage Boundary Confirmation

- **Stage 8 — Decision & Reasoning Agent**: **COMPLETE**
- **Stage 9 — Dashboard & Audit Trail**: **NOT IMPLEMENTED** (Scheduled for next stage)
