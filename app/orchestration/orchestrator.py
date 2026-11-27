"""Underwriting Orchestrator Engine.

Coordinates the specialized multi-agent pipeline in dependency order:
1. Document processing (DocumentIntakeAgent)
2. Applicant data validation (validate_applicant_data)
3. Eligibility assessment (EligibilityAgent)
4. Fraud and cross-document consistency assessment (FraudAnomalyAgent)
5. Credit risk assessment (RiskAgent)
6. Cross-agent output consistency verification (check_cross_agent_consistency)
7. Structured aggregation (and optional Stage 8 decision + Stage 9 audit persistence)

Preserves fault tolerance, controlled error states, partial-result safety, and
deterministic ordering without fabricating failed agent outputs.
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

from app.agents.document_agent import DocumentIntakeAgent
from app.agents.eligibility_agent import EligibilityAgent
from app.agents.fraud_agent import FraudAnomalyAgent
from app.agents.risk_agent import RiskAgent
from app.document_processing.document_package import (
    SALARIED_REQUIRED_DOCS,
    SELF_EMPLOYED_REQUIRED_DOCS,
)
from app.orchestration.consistency import (
    AUTHORITATIVE_SOURCES,
    check_cross_agent_consistency,
    validate_anomaly_output,
    validate_applicant_data,
    validate_document_output,
    validate_eligibility_output,
    validate_risk_output,
)
from app.schemas.anomaly import AnomalyResult
from app.schemas.applicant import (
    Applicant,
    Document,
    DocumentPackageResult,
    EligibilityResult,
    RiskResult,
)
from app.schemas.underwriting import (
    AgentExecutionStatus,
    AgentStatus,
    OrchestrationStatus,
    UnderwritingAnalysisResult,
)
from app.utils.helpers import get_logger

if TYPE_CHECKING:
    from app.agents.decision_agent import DecisionReasoningAgent
    from app.schemas.decision import DecisionReasoningResult

logger = get_logger(__name__)

DEFAULT_APPLICANTS_JSON = os.path.join("data", "synthetic_data", "applicants.json")
DEFAULT_DOCUMENTS_DIR = os.path.join("data", "documents")
ORCHESTRATOR_VERSION = "pipeline_v1"


class UnderwritingOrchestrator:
    """Master orchestrator coordinating specialized underwriting agents."""

    def __init__(
        self,
        document_agent: Optional[DocumentIntakeAgent] = None,
        eligibility_agent: Optional[EligibilityAgent] = None,
        risk_agent: Optional[RiskAgent] = None,
        fraud_agent: Optional[FraudAnomalyAgent] = None,
        applicants_data_path: Optional[str] = None,
        documents_dir: Optional[str] = None,
        pipeline_version: str = ORCHESTRATOR_VERSION,
    ) -> None:
        """Initialize UnderwritingOrchestrator with agents and configuration."""
        self.document_agent = document_agent or DocumentIntakeAgent()
        self.eligibility_agent = eligibility_agent or EligibilityAgent()
        self.risk_agent = risk_agent or RiskAgent()
        self.fraud_agent = fraud_agent or FraudAnomalyAgent()
        self.applicants_data_path = applicants_data_path or DEFAULT_APPLICANTS_JSON
        self.documents_dir = documents_dir or DEFAULT_DOCUMENTS_DIR
        self.pipeline_version = pipeline_version
        self._applicant_cache: Optional[Dict[str, Dict[str, Any]]] = None

        logger.info(
            "UnderwritingOrchestrator initialized (Version: %s).",
            self.pipeline_version,
        )

    def process(
        self,
        application_id: str,
        package_dir: Optional[str] = None,
    ) -> UnderwritingAnalysisResult:
        """Execute the deterministic analytical underwriting pipeline for application_id."""
        pipeline_start_utc = datetime.now(timezone.utc)
        pipeline_start_perf = time.perf_counter()

        logger.info(
            "Starting underwriting pipeline for application '%s'.", application_id
        )

        agent_statuses: Dict[str, AgentExecutionStatus] = {}
        document_result: Optional[DocumentPackageResult] = None
        eligibility_result: Optional[EligibilityResult] = None
        fraud_result: Optional[AnomalyResult] = None
        risk_result: Optional[RiskResult] = None

        # -------------------------------------------------------------------
        # Step 0: Locate Applicant Profile
        # -------------------------------------------------------------------
        applicant = self.load_applicant(application_id)
        if not applicant:
            logger.error("Applicant '%s' not found in dataset.", application_id)
            total_duration_ms = (time.perf_counter() - pipeline_start_perf) * 1000.0
            return UnderwritingAnalysisResult(
                application_id=application_id,
                applicant_id=application_id,
                orchestration_status=OrchestrationStatus.FAILED,
                error_message=(
                    f"Applicant profile not found for identifier: '{application_id}'."
                ),
                agent_statuses={},
                authoritative_sources=dict(AUTHORITATIVE_SOURCES),
                has_unresolved_conflicts=True,
                pipeline_started_at=pipeline_start_utc,
                pipeline_completed_at=datetime.now(timezone.utc),
                total_duration_ms=round(total_duration_ms, 2),
                pipeline_version=self.pipeline_version,
                summary=(
                    f"Pipeline FAILED for {application_id}: Applicant record could not be "
                    "located in database or dataset."
                ),
            )

        # -------------------------------------------------------------------
        # Step 1: Document Processing (DocumentIntakeAgent)
        # -------------------------------------------------------------------
        doc_dir = package_dir or os.path.join(self.documents_dir, application_id)
        doc_status = AgentExecutionStatus(
            agent_name="document_agent",
            status=AgentStatus.RUNNING,
            input_reference=f"applicant_id:{application_id}|package_dir:{doc_dir}",
            started_at=datetime.now(timezone.utc),
        )
        doc_start_perf = time.perf_counter()
        try:
            raw_doc_res = self.document_agent.process_package(
                applicant_id=application_id, package_dir=doc_dir
            )
            document_result = validate_document_output(raw_doc_res, application_id)
            doc_duration = (time.perf_counter() - doc_start_perf) * 1000.0
            doc_status.completed_at = datetime.now(timezone.utc)
            doc_status.duration_ms = round(doc_duration, 2)
            doc_status.output_available = True

            doc_warnings: List[str] = []
            if document_result.documents_missing:
                doc_warnings.append(
                    f"Missing required document(s): {', '.join(sorted(document_result.documents_missing))}"
                )
            if document_result.unclassified_documents:
                doc_warnings.append(
                    f"Unclassified document(s): {', '.join(sorted(document_result.unclassified_documents))}"
                )
            if document_result.invalid_fields:
                doc_warnings.append(
                    f"Invalid extracted fields in: {', '.join(sorted(document_result.invalid_fields.keys()))}"
                )
            if document_result.ambiguous_fields:
                doc_warnings.append(
                    f"Ambiguous extracted fields in: {', '.join(sorted(document_result.ambiguous_fields.keys()))}"
                )
            if document_result.field_conflicts:
                doc_warnings.append(
                    f"Intra-package conflicts: {', '.join(sorted(document_result.field_conflicts.keys()))}"
                )

            doc_status.warnings = doc_warnings
            doc_status.evidence_references = sorted(
                d.document_id for d in document_result.documents_found
            )

            if document_result.processing_status == "failed":
                doc_status.status = AgentStatus.FAILED
                doc_status.success = False
            else:
                doc_status.status = AgentStatus.SUCCESS
                doc_status.success = True

            if document_result.processing_errors:
                doc_status.error = "; ".join(document_result.processing_errors)

            logger.info(
                "Document Intelligence completed for '%s' in %.2fms (Found: %d, Missing: %d).",
                application_id,
                doc_duration,
                len(document_result.documents_found),
                len(document_result.documents_missing),
            )
        except Exception as exc:
            doc_duration = (time.perf_counter() - doc_start_perf) * 1000.0
            document_result = None
            doc_status.completed_at = datetime.now(timezone.utc)
            doc_status.duration_ms = round(doc_duration, 2)
            doc_status.status = AgentStatus.FAILED
            doc_status.success = False
            doc_status.output_available = False
            doc_status.error = str(exc)
            logger.error("Document agent failed for '%s': %s", application_id, exc)

        agent_statuses["document_agent"] = doc_status

        # -------------------------------------------------------------------
        # Step 2: Applicant Data Validation
        # -------------------------------------------------------------------
        validation_warnings: List[str] = []
        applicant_valid = True
        try:
            validation_warnings = validate_applicant_data(applicant)
        except Exception as exc:
            applicant_valid = False
            validation_warnings = [f"Applicant validation error: {exc}"]
            logger.error(
                "Applicant validation failed for '%s': %s", application_id, exc
            )

        # -------------------------------------------------------------------
        # Step 3: Eligibility Assessment (Downstream of Document Intelligence)
        # -------------------------------------------------------------------
        elig_status = AgentExecutionStatus(
            agent_name="eligibility_agent",
            status=AgentStatus.RUNNING,
            input_reference=(
                f"DocumentPackageResult:{application_id}"
                if self._has_usable_document_package(document_result)
                else f"ApplicantFallback:{application_id}"
            ),
            started_at=datetime.now(timezone.utc),
        )
        elig_start_perf = time.perf_counter()
        if not applicant_valid:
            elig_status.completed_at = datetime.now(timezone.utc)
            elig_status.duration_ms = 0.0
            elig_status.status = AgentStatus.SKIPPED
            elig_status.success = False
            elig_status.output_available = False
            elig_status.error = "; ".join(validation_warnings)
        else:
            try:
                if self._has_usable_document_package(document_result):
                    target_for_elig: Any = document_result
                else:
                    target_for_elig = self._build_eligibility_fallback_target(
                        applicant=applicant, document_result=document_result
                    )
                    elig_status.warnings.append(
                        "Evaluated eligibility from Applicant fallback due to missing/failed document extraction."
                    )

                raw_elig_res = self.eligibility_agent.evaluate(target_for_elig)
                eligibility_result = validate_eligibility_output(
                    raw_elig_res, application_id
                )
                elig_duration = (time.perf_counter() - elig_start_perf) * 1000.0
                elig_status.completed_at = datetime.now(timezone.utc)
                elig_status.duration_ms = round(elig_duration, 2)
                elig_status.status = AgentStatus.SUCCESS
                elig_status.success = True
                elig_status.output_available = True
                elig_status.evidence_references = sorted(
                    eligibility_result.rules_evaluated
                )
                logger.info(
                    "Eligibility evaluation completed for '%s' in %.2fms (Status: %s).",
                    application_id,
                    elig_duration,
                    eligibility_result.status.value,
                )
            except Exception as exc:
                elig_duration = (time.perf_counter() - elig_start_perf) * 1000.0
                eligibility_result = None
                elig_status.completed_at = datetime.now(timezone.utc)
                elig_status.duration_ms = round(elig_duration, 2)
                elig_status.status = AgentStatus.FAILED
                elig_status.success = False
                elig_status.output_available = False
                elig_status.error = str(exc)
                logger.error(
                    "Eligibility agent failed for '%s': %s", application_id, exc
                )

        agent_statuses["eligibility_agent"] = elig_status

        # -------------------------------------------------------------------
        # Step 4: Fraud & Anomaly Assessment (Downstream of Document Intelligence)
        # -------------------------------------------------------------------
        anomaly_status = AgentExecutionStatus(
            agent_name="anomaly_agent",
            status=AgentStatus.RUNNING,
            input_reference=(
                f"DocumentPackageResult:{application_id}"
                if document_result is not None
                else f"MissingDocumentsSentinel:{application_id}"
            ),
            started_at=datetime.now(timezone.utc),
        )
        anomaly_start_perf = time.perf_counter()
        try:
            # Never pass pure Applicant vs Applicant as if documents were verified cleanly:
            # when document intake returned None, supply a failed empty sentinel carrying missing docs.
            if document_result is not None:
                target_for_anomaly = document_result
            else:
                expected_docs = self._expected_documents_for_applicant(applicant)
                target_for_anomaly = DocumentPackageResult(
                    applicant_id=application_id,
                    package_dir=doc_dir,
                    documents_found=[],
                    documents_missing=expected_docs,
                    expected_documents=expected_docs,
                    is_complete=False,
                    processing_status="failed",
                    processing_errors=[
                        "Document intake failed prior to anomaly detection."
                    ],
                    all_extracted_fields={},
                )
                anomaly_status.warnings.append(
                    "Document intake failed; anomaly verification ran with missing-document sentinel."
                )

            raw_anom_res = self.fraud_agent.detect(
                target_for_anomaly, applicant_profile=applicant
            )
            fraud_result = validate_anomaly_output(raw_anom_res, application_id)
            if fraud_result.flags:
                fraud_result.flags = sorted(
                    fraud_result.flags, key=lambda f: (f.rule_id, f.anomaly_type)
                )
            if fraud_result.missing_evidence:
                fraud_result.missing_evidence = sorted(fraud_result.missing_evidence)

            anomaly_duration = (time.perf_counter() - anomaly_start_perf) * 1000.0
            anomaly_status.completed_at = datetime.now(timezone.utc)
            anomaly_status.duration_ms = round(anomaly_duration, 2)
            anomaly_status.status = AgentStatus.SUCCESS
            anomaly_status.success = True
            anomaly_status.output_available = True
            anomaly_status.evidence_references = sorted(
                f.rule_id for f in fraud_result.flags
            )
            logger.info(
                "Anomaly detection completed for '%s' in %.2fms (Anomalies: %s, Flags: %d).",
                application_id,
                anomaly_duration,
                fraud_result.has_anomalies,
                len(fraud_result.flags),
            )
        except Exception as exc:
            anomaly_duration = (time.perf_counter() - anomaly_start_perf) * 1000.0
            fraud_result = None
            anomaly_status.completed_at = datetime.now(timezone.utc)
            anomaly_status.duration_ms = round(anomaly_duration, 2)
            anomaly_status.status = AgentStatus.FAILED
            anomaly_status.success = False
            anomaly_status.output_available = False
            anomaly_status.error = str(exc)
            logger.error("Anomaly agent failed for '%s': %s", application_id, exc)

        agent_statuses["anomaly_agent"] = anomaly_status

        # -------------------------------------------------------------------
        # Step 5: Risk Assessment (Independent ML + Rule Factor Scoring)
        # -------------------------------------------------------------------
        risk_status = AgentExecutionStatus(
            agent_name="risk_agent",
            status=AgentStatus.RUNNING,
            input_reference=f"Applicant:{application_id}",
            started_at=datetime.now(timezone.utc),
        )
        risk_start_perf = time.perf_counter()
        if not applicant_valid:
            risk_status.completed_at = datetime.now(timezone.utc)
            risk_status.duration_ms = 0.0
            risk_status.status = AgentStatus.SKIPPED
            risk_status.success = False
            risk_status.output_available = False
            risk_status.error = "; ".join(validation_warnings)
        else:
            try:
                raw_risk_res = self.risk_agent.assess(applicant)
                risk_result = validate_risk_output(raw_risk_res, application_id)
                risk_duration = (time.perf_counter() - risk_start_perf) * 1000.0
                risk_status.completed_at = datetime.now(timezone.utc)
                risk_status.duration_ms = round(risk_duration, 2)
                risk_status.status = AgentStatus.SUCCESS
                risk_status.success = True
                risk_status.output_available = True
                risk_status.evidence_references = [risk_result.model_version]
                logger.info(
                    "Risk assessment completed for '%s' in %.2fms (Score: %.1f, Tier: %s).",
                    application_id,
                    risk_duration,
                    risk_result.risk_score,
                    risk_result.risk_category.value,
                )
            except Exception as exc:
                risk_duration = (time.perf_counter() - risk_start_perf) * 1000.0
                risk_result = None
                risk_status.completed_at = datetime.now(timezone.utc)
                risk_status.duration_ms = round(risk_duration, 2)
                risk_status.status = AgentStatus.FAILED
                risk_status.success = False
                risk_status.output_available = False
                risk_status.error = str(exc)
                logger.error("Risk agent failed for '%s': %s", application_id, exc)

        agent_statuses["risk_agent"] = risk_status

        # -------------------------------------------------------------------
        # Step 6: Overall Orchestration Status
        # -------------------------------------------------------------------
        total_duration_ms = (time.perf_counter() - pipeline_start_perf) * 1000.0
        success_count = sum(
            1 for st in agent_statuses.values() if st.status == AgentStatus.SUCCESS
        )
        failed_count = sum(
            1
            for st in agent_statuses.values()
            if st.status in (AgentStatus.FAILED, AgentStatus.SKIPPED)
        )

        if (
            success_count == len(agent_statuses)
            and failed_count == 0
            and applicant_valid
        ):
            orch_status = OrchestrationStatus.SUCCESS
            error_message = None
        elif success_count > 0:
            orch_status = OrchestrationStatus.PARTIAL_SUCCESS
            failed_agents = [
                name
                for name, st in agent_statuses.items()
                if st.status in (AgentStatus.FAILED, AgentStatus.SKIPPED)
            ]
            error_message = f"Partial pipeline completion. Failed/skipped agents: {', '.join(failed_agents)}."
        else:
            orch_status = OrchestrationStatus.FAILED
            error_message = "All specialized agents failed execution."

        # -------------------------------------------------------------------
        # Step 7: Build Provisional Result & Run Cross-Agent Consistency Check
        # -------------------------------------------------------------------
        prelim_summary = self._synthesize_summary(
            application_id=application_id,
            orch_status=orch_status,
            doc_result=document_result,
            elig_result=eligibility_result,
            risk_result=risk_result,
            anom_result=fraud_result,
            agent_statuses=agent_statuses,
        )

        analysis = UnderwritingAnalysisResult(
            application_id=application_id,
            applicant_id=application_id,
            orchestration_status=orch_status,
            document_result=document_result,
            eligibility_result=eligibility_result,
            risk_result=risk_result,
            anomaly_result=fraud_result,
            agent_statuses=agent_statuses,
            validation_warnings=validation_warnings,
            pipeline_started_at=pipeline_start_utc,
            pipeline_completed_at=datetime.now(timezone.utc),
            total_duration_ms=round(total_duration_ms, 2),
            pipeline_version=self.pipeline_version,
            error_message=error_message,
            summary=prelim_summary,
        )

        auth_sources, conflicts = check_cross_agent_consistency(
            analysis, applicant=applicant
        )
        analysis.authoritative_sources = auth_sources
        analysis.consistency_conflicts = conflicts
        analysis.has_unresolved_conflicts = any(
            c.get("severity") == "BLOCKING" for c in conflicts
        )

        logger.info(
            "Pipeline finished for '%s' (Status: %s, Conflicts: %d, Total Duration: %.2fms).",
            application_id,
            orch_status.value,
            len(conflicts),
            total_duration_ms,
        )

        return analysis

    def execute_end_to_end(
        self,
        application_id: str,
        package_dir: Optional[str] = None,
        decision_agent: Optional["DecisionReasoningAgent"] = None,
        persist_audit: bool = True,
    ) -> Tuple[UnderwritingAnalysisResult, "DecisionReasoningResult"]:
        """Execute full Steps 1-7 pipeline: analysis -> decision -> safe audit persistence."""
        from app.agents.decision_agent import DecisionReasoningAgent
        from app.database.audit import save_underwriting_run_safe

        analysis = self.process(application_id=application_id, package_dir=package_dir)
        dec_agent = decision_agent or DecisionReasoningAgent()
        decision = dec_agent.evaluate(analysis)

        if persist_audit:
            run_id, db_err = save_underwriting_run_safe(
                analysis=analysis,
                decision=decision,
                execution_time_ms=float(analysis.total_duration_ms or 0.0),
            )
            analysis.audit_run_id = run_id
            analysis.audit_persisted = run_id is not None and db_err is None
            analysis.audit_persistence_error = db_err

        return analysis, decision

    def run(
        self,
        application_id: str,
        package_dir: Optional[str] = None,
    ) -> UnderwritingAnalysisResult:
        """Alias for process()."""
        return self.process(application_id=application_id, package_dir=package_dir)

    def run_pipeline(
        self,
        applicant: Applicant,
        documents: Optional[List[Document]] = None,
        package_dir: Optional[str] = None,
    ) -> UnderwritingAnalysisResult:
        """Execute underwriting pipeline for a pre-loaded Applicant domain model."""
        if self._applicant_cache is None:
            self._init_applicant_cache()
        if self._applicant_cache is not None:
            self._applicant_cache[applicant.applicant_id] = applicant.model_dump()

        return self.process(
            application_id=applicant.applicant_id, package_dir=package_dir
        )

    # -----------------------------------------------------------------------
    # Helper Methods
    # -----------------------------------------------------------------------

    @staticmethod
    def _has_usable_document_package(
        document_result: Optional[DocumentPackageResult],
    ) -> bool:
        """Return True only when document intake succeeded with usable extracted fields."""
        if document_result is None:
            return False
        if document_result.processing_status == "failed":
            return False
        if not document_result.documents_found:
            return False
        if not document_result.all_extracted_fields:
            return False
        return True

    @staticmethod
    def _expected_documents_for_applicant(applicant: Applicant) -> List[str]:
        """Determine expected required document types from the applicant profile."""
        emp = str(applicant.employment_type).lower()
        if "self" in emp or "business" in emp:
            return list(SELF_EMPLOYED_REQUIRED_DOCS)
        return list(SALARIED_REQUIRED_DOCS)

    def _build_eligibility_fallback_target(
        self,
        applicant: Applicant,
        document_result: Optional[DocumentPackageResult],
    ) -> Dict[str, Any]:
        """Build an Applicant-backed eligibility payload preserving missing-document state."""
        payload = applicant.model_dump()
        expected_docs = self._expected_documents_for_applicant(applicant)

        if document_result is not None:
            found_types = [d.document_type for d in document_result.documents_found]
            if document_result.documents_missing:
                missing_docs = sorted(document_result.documents_missing)
            else:
                missing_docs = sorted(
                    d for d in expected_docs if d not in set(found_types)
                )
        else:
            found_types = []
            missing_docs = sorted(expected_docs)

        payload["documents_found"] = found_types
        payload["documents_missing"] = missing_docs
        payload["is_complete"] = False
        return payload

    def load_applicant(self, application_id: str) -> Optional[Applicant]:
        """Load applicant structured information from dataset or cache."""
        if self._applicant_cache is None:
            self._init_applicant_cache()

        raw_data = (
            self._applicant_cache.get(application_id) if self._applicant_cache else None
        )
        if not raw_data:
            return None

        try:
            return Applicant.model_validate(raw_data)
        except Exception as exc:
            logger.warning(
                "Failed to parse applicant '%s' with strict schema: %s. Attempting normalized conversion.",
                application_id,
                exc,
            )
            clean_data = dict(raw_data)
            if "employment_type" in clean_data and isinstance(
                clean_data["employment_type"], str
            ):
                clean_data["employment_type"] = clean_data[
                    "employment_type"
                ].capitalize()
            return Applicant.model_validate(clean_data)

    def _init_applicant_cache(self) -> None:
        """Load applicants from synthetic dataset into memory cache."""
        self._applicant_cache = {}
        if not os.path.exists(self.applicants_data_path):
            logger.warning(
                "Applicant dataset not found at '%s'.", self.applicants_data_path
            )
            return

        try:
            with open(self.applicants_data_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    for item in data:
                        app_id = item.get("applicant_id")
                        if app_id:
                            self._applicant_cache[app_id] = item
                elif isinstance(data, dict):
                    self._applicant_cache = data
            logger.info(
                "Loaded %d applicants into orchestrator cache from '%s'.",
                len(self._applicant_cache),
                self.applicants_data_path,
            )
        except Exception as exc:
            logger.error("Error reading applicants dataset: %s", exc)

    def _synthesize_summary(
        self,
        application_id: str,
        orch_status: OrchestrationStatus,
        doc_result: Optional[DocumentPackageResult],
        elig_result: Optional[EligibilityResult],
        risk_result: Optional[RiskResult],
        anom_result: Optional[AnomalyResult],
        agent_statuses: Dict[str, AgentExecutionStatus],
    ) -> str:
        """Synthesize human-readable executive analytical findings across all agents."""
        parts: List[str] = [
            f"Underwriting Pipeline Analysis for {application_id} (Status: {orch_status.value})."
        ]

        if doc_result:
            parts.append(
                f"Documents: {len(doc_result.documents_found)} verified, "
                f"{len(doc_result.documents_missing)} missing."
            )
        elif "document_agent" in agent_statuses:
            parts.append(
                f"Documents: Agent {agent_statuses['document_agent'].status.value}."
            )

        if elig_result:
            parts.append(f"Eligibility: {elig_result.status.value}.")
        elif "eligibility_agent" in agent_statuses:
            parts.append(
                f"Eligibility: Agent {agent_statuses['eligibility_agent'].status.value}."
            )

        if risk_result:
            parts.append(
                f"Risk Assessment: {risk_result.risk_category.value} (Score: {risk_result.risk_score:.1f}/100)."
            )
        elif "risk_agent" in agent_statuses:
            parts.append(
                f"Risk Assessment: Agent {agent_statuses['risk_agent'].status.value}."
            )

        if anom_result:
            parts.append(
                f"Anomaly Detection: {anom_result.severity.value} "
                f"(Score: {anom_result.anomaly_score:.1f}/100, Flags: {len(anom_result.flags)})."
            )
        elif "anomaly_agent" in agent_statuses:
            parts.append(
                f"Anomaly Detection: Agent {agent_statuses['anomaly_agent'].status.value}."
            )

        parts.append(
            "Notice: Final loan recommendation (APPROVE/REJECT/MANUAL_REVIEW) pending Stage 8 Decision & Reasoning Agent."
        )

        return " ".join(parts)


__all__ = ["UnderwritingOrchestrator", "ORCHESTRATOR_VERSION"]
