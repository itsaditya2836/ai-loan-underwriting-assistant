"""Underwriting Orchestrator Engine.

Coordinates the specialized multi-agent pipeline for loan underwriting:
1. Loads applicant profile from synthetic dataset or database.
2. Ingests and processes submitted documents (DocumentIntakeAgent).
3. Evaluates underwriting eligibility rules (EligibilityAgent).
4. Assesses financial and credit risk (RiskAgent).
5. Cross-verifies documents for anomalies and inconsistencies (FraudAnomalyAgent).
6. Aggregates findings into a unified, audit-ready UnderwritingAnalysisResult.

Strictly preserves architectural boundaries: Stage 7 performs orchestration
and analytical aggregation; final loan decisioning is reserved for Stage 8.
"""

import json
import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.agents.document_agent import DocumentIntakeAgent
from app.agents.eligibility_agent import EligibilityAgent
from app.agents.fraud_agent import FraudAnomalyAgent
from app.agents.risk_agent import RiskAgent
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

logger = get_logger(__name__)

DEFAULT_APPLICANTS_JSON = os.path.join("data", "synthetic_data", "applicants.json")
DEFAULT_DOCUMENTS_DIR = os.path.join("data", "documents")
ORCHESTRATOR_VERSION = "pipeline_v1"


class UnderwritingOrchestrator:
    """Master orchestrator coordinating specialized underwriting agents.

    Executes a deterministic pipeline across Document Intelligence, Underwriting
    Eligibility, Risk Assessment, and Anomaly Detection agents.
    Provides robust failure isolation, partial-result preservation, and telemetry tracking.
    """

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
        """Execute the underwriting pipeline for an application identifier.

        Args:
            application_id: Unique applicant or application ID (e.g. 'APP0001').
            package_dir: Optional custom document directory. If omitted,
                defaults to 'data/documents/{application_id}'.

        Returns:
            UnderwritingAnalysisResult aggregating findings from all agents.
        """
        pipeline_start_utc = datetime.now(timezone.utc)
        pipeline_start_perf = time.perf_counter()

        logger.info(
            "Starting underwriting pipeline for application '%s'.", application_id
        )

        agent_statuses: Dict[str, AgentExecutionStatus] = {}
        document_result: Optional[DocumentPackageResult] = None
        eligibility_result: Optional[EligibilityResult] = None
        risk_result: Optional[RiskResult] = None
        anomaly_result: Optional[AnomalyResult] = None

        # -------------------------------------------------------------------
        # Step 1: Load Applicant Profile
        # -------------------------------------------------------------------
        applicant = self.load_applicant(application_id)
        if not applicant:
            logger.error(
                "Applicant '%s' not found in synthetic dataset.", application_id
            )
            total_duration_ms = (time.perf_counter() - pipeline_start_perf) * 1000.0
            return UnderwritingAnalysisResult(
                application_id=application_id,
                applicant_id=application_id,
                orchestration_status=OrchestrationStatus.FAILED,
                error_message=f"Applicant profile not found for identifier: '{application_id}'.",
                agent_statuses={},
                pipeline_started_at=pipeline_start_utc,
                pipeline_completed_at=datetime.now(timezone.utc),
                total_duration_ms=round(total_duration_ms, 2),
                pipeline_version=self.pipeline_version,
                summary=(
                    f"Pipeline FAILED for {application_id}: Applicant record could not be located in database or dataset."
                ),
            )

        # -------------------------------------------------------------------
        # Step 2: Document Intelligence Agent
        # -------------------------------------------------------------------
        doc_dir = package_dir or os.path.join(self.documents_dir, application_id)
        doc_status = AgentExecutionStatus(
            agent_name="document_agent",
            status=AgentStatus.RUNNING,
            started_at=datetime.now(timezone.utc),
        )
        doc_start_perf = time.perf_counter()
        try:
            document_result = self.document_agent.process_package(
                applicant_id=application_id, package_dir=doc_dir
            )
            doc_duration = (time.perf_counter() - doc_start_perf) * 1000.0
            doc_status.completed_at = datetime.now(timezone.utc)
            doc_status.duration_ms = round(doc_duration, 2)
            doc_status.status = (
                AgentStatus.SUCCESS
                if document_result.processing_status != "failed"
                else AgentStatus.FAILED
            )
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
            doc_status.completed_at = datetime.now(timezone.utc)
            doc_status.duration_ms = round(doc_duration, 2)
            doc_status.status = AgentStatus.FAILED
            doc_status.error = str(exc)
            logger.error("Document agent failed for '%s': %s", application_id, exc)

        agent_statuses["document_agent"] = doc_status

        # -------------------------------------------------------------------
        # Step 3: Eligibility Agent (Downstream of Document Intelligence)
        # -------------------------------------------------------------------
        elig_status = AgentExecutionStatus(
            agent_name="eligibility_agent",
            status=AgentStatus.RUNNING,
            started_at=datetime.now(timezone.utc),
        )
        elig_start_perf = time.perf_counter()
        try:
            # Pass document result if present; otherwise fall back to applicant profile
            target_for_elig = document_result if document_result else applicant
            eligibility_result = self.eligibility_agent.evaluate(target_for_elig)
            elig_duration = (time.perf_counter() - elig_start_perf) * 1000.0
            elig_status.completed_at = datetime.now(timezone.utc)
            elig_status.duration_ms = round(elig_duration, 2)
            elig_status.status = AgentStatus.SUCCESS
            logger.info(
                "Eligibility evaluation completed for '%s' in %.2fms (Status: %s).",
                application_id,
                elig_duration,
                eligibility_result.status.value,
            )
        except Exception as exc:
            elig_duration = (time.perf_counter() - elig_start_perf) * 1000.0
            elig_status.completed_at = datetime.now(timezone.utc)
            elig_status.duration_ms = round(elig_duration, 2)
            elig_status.status = AgentStatus.FAILED
            elig_status.error = str(exc)
            logger.error("Eligibility agent failed for '%s': %s", application_id, exc)

        agent_statuses["eligibility_agent"] = elig_status

        # -------------------------------------------------------------------
        # Step 4: Risk Assessment Agent (Independent on Applicant Profile)
        # -------------------------------------------------------------------
        risk_status = AgentExecutionStatus(
            agent_name="risk_agent",
            status=AgentStatus.RUNNING,
            started_at=datetime.now(timezone.utc),
        )
        risk_start_perf = time.perf_counter()
        try:
            risk_result = self.risk_agent.assess(applicant)
            risk_duration = (time.perf_counter() - risk_start_perf) * 1000.0
            risk_status.completed_at = datetime.now(timezone.utc)
            risk_status.duration_ms = round(risk_duration, 2)
            risk_status.status = AgentStatus.SUCCESS
            logger.info(
                "Risk assessment completed for '%s' in %.2fms (Score: %.1f, Tier: %s).",
                application_id,
                risk_duration,
                risk_result.risk_score,
                risk_result.risk_category.value,
            )
        except Exception as exc:
            risk_duration = (time.perf_counter() - risk_start_perf) * 1000.0
            risk_status.completed_at = datetime.now(timezone.utc)
            risk_status.duration_ms = round(risk_duration, 2)
            risk_status.status = AgentStatus.FAILED
            risk_status.error = str(exc)
            logger.error("Risk agent failed for '%s': %s", application_id, exc)

        agent_statuses["risk_agent"] = risk_status

        # -------------------------------------------------------------------
        # Step 5: Fraud & Anomaly Detection Agent (Consumes Docs + Applicant)
        # -------------------------------------------------------------------
        anomaly_status = AgentExecutionStatus(
            agent_name="anomaly_agent",
            status=AgentStatus.RUNNING,
            started_at=datetime.now(timezone.utc),
        )
        anomaly_start_perf = time.perf_counter()
        try:
            target_for_anomaly = document_result if document_result else applicant
            anomaly_result = self.fraud_agent.detect(
                target_for_anomaly, applicant_profile=applicant
            )
            # Ensure deterministic order of flags by rule_id
            if anomaly_result.flags:
                anomaly_result.flags = sorted(
                    anomaly_result.flags, key=lambda f: f.rule_id
                )
            anomaly_duration = (time.perf_counter() - anomaly_start_perf) * 1000.0
            anomaly_status.completed_at = datetime.now(timezone.utc)
            anomaly_status.duration_ms = round(anomaly_duration, 2)
            anomaly_status.status = AgentStatus.SUCCESS
            logger.info(
                "Anomaly detection completed for '%s' in %.2fms (Anomalies: %s, Flags: %d).",
                application_id,
                anomaly_duration,
                anomaly_result.has_anomalies,
                len(anomaly_result.flags),
            )
        except Exception as exc:
            anomaly_duration = (time.perf_counter() - anomaly_start_perf) * 1000.0
            anomaly_status.completed_at = datetime.now(timezone.utc)
            anomaly_status.duration_ms = round(anomaly_duration, 2)
            anomaly_status.status = AgentStatus.FAILED
            anomaly_status.error = str(exc)
            logger.error("Anomaly agent failed for '%s': %s", application_id, exc)

        agent_statuses["anomaly_agent"] = anomaly_status

        # -------------------------------------------------------------------
        # Step 6: Determine Overall Orchestration Lifecycle Status
        # -------------------------------------------------------------------
        total_duration_ms = (time.perf_counter() - pipeline_start_perf) * 1000.0
        success_count = sum(
            1 for st in agent_statuses.values() if st.status == AgentStatus.SUCCESS
        )
        failed_count = sum(
            1 for st in agent_statuses.values() if st.status == AgentStatus.FAILED
        )

        if success_count == len(agent_statuses) and failed_count == 0:
            orch_status = OrchestrationStatus.SUCCESS
            error_message = None
        elif success_count > 0:
            orch_status = OrchestrationStatus.PARTIAL_SUCCESS
            failed_agents = [
                name
                for name, st in agent_statuses.items()
                if st.status == AgentStatus.FAILED
            ]
            error_message = f"Partial pipeline completion. Failed agents: {', '.join(failed_agents)}."
        else:
            orch_status = OrchestrationStatus.FAILED
            error_message = "All specialized agents failed execution."

        # -------------------------------------------------------------------
        # Step 7: Synthesize Executive Analytical Summary
        # -------------------------------------------------------------------
        summary = self._synthesize_summary(
            application_id=application_id,
            orch_status=orch_status,
            doc_result=document_result,
            elig_result=eligibility_result,
            risk_result=risk_result,
            anom_result=anomaly_result,
            agent_statuses=agent_statuses,
        )

        logger.info(
            "Pipeline finished for '%s' (Status: %s, Total Duration: %.2fms).",
            application_id,
            orch_status.value,
            total_duration_ms,
        )

        return UnderwritingAnalysisResult(
            application_id=application_id,
            applicant_id=application_id,
            orchestration_status=orch_status,
            document_result=document_result,
            eligibility_result=eligibility_result,
            risk_result=risk_result,
            anomaly_result=anomaly_result,
            agent_statuses=agent_statuses,
            pipeline_started_at=pipeline_start_utc,
            pipeline_completed_at=datetime.now(timezone.utc),
            total_duration_ms=round(total_duration_ms, 2),
            pipeline_version=self.pipeline_version,
            error_message=error_message,
            summary=summary,
        )

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
        """Execute underwriting pipeline for a pre-loaded Applicant domain model.

        Args:
            applicant: Pre-loaded Applicant domain model.
            documents: Optional list of Document objects (for legacy compatibility).
            package_dir: Optional path to physical document package directory.

        Returns:
            UnderwritingAnalysisResult.
        """
        # Seed applicant into cache to allow immediate lookup
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
            # Normalize casing for employment_type if needed
            clean_data = dict(raw_data)
            if "employment_type" in clean_data and isinstance(
                clean_data["employment_type"], str
            ):
                emp_str = clean_data["employment_type"].capitalize()
                clean_data["employment_type"] = emp_str
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

        # Document findings
        if doc_result:
            parts.append(
                f"Documents: {len(doc_result.documents_found)} verified, "
                f"{len(doc_result.documents_missing)} missing."
            )
        elif "document_agent" in agent_statuses:
            parts.append(
                f"Documents: Agent {agent_statuses['document_agent'].status.value}."
            )

        # Eligibility findings
        if elig_result:
            parts.append(f"Eligibility: {elig_result.status.value}.")
        elif "eligibility_agent" in agent_statuses:
            parts.append(
                f"Eligibility: Agent {agent_statuses['eligibility_agent'].status.value}."
            )

        # Risk findings
        if risk_result:
            parts.append(
                f"Risk Assessment: {risk_result.risk_category.value} (Score: {risk_result.risk_score:.1f}/100)."
            )
        elif "risk_agent" in agent_statuses:
            parts.append(
                f"Risk Assessment: Agent {agent_statuses['risk_agent'].status.value}."
            )

        # Anomaly findings
        if anom_result:
            parts.append(
                f"Anomaly Detection: {anom_result.severity.value} "
                f"(Score: {anom_result.anomaly_score:.1f}/100, Flags: {len(anom_result.flags)})."
            )
        elif "anomaly_agent" in agent_statuses:
            parts.append(
                f"Anomaly Detection: Agent {agent_statuses['anomaly_agent'].status.value}."
            )

        # Stage boundary reminder
        parts.append(
            "Notice: Final loan recommendation (APPROVE/REJECT/MANUAL_REVIEW) pending Stage 8 Decision & Reasoning Agent."
        )

        return " ".join(parts)


__all__ = ["UnderwritingOrchestrator", "ORCHESTRATOR_VERSION"]
