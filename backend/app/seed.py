from datetime import date

from sqlalchemy.orm import Session

from .models import AiUsage, BudgetAlert, CloudSpend, ClusterConnection, Customer, Invoice, KubernetesCost


def seed_if_empty(db: Session) -> None:
    if db.query(Customer).first():
        existing = {cluster.cluster_name for cluster in db.query(ClusterConnection).all()}
        customers = {customer.name: customer.id for customer in db.query(Customer).all()}
        demo_clusters = [
            ("AstraPay Fintech", "prod-mumbai", "AWS EKS", "Production", "cm_prod_mumbai_demo", "connected", "2 minutes ago"),
            ("NilaCloud MSP", "client-fleet-01", "OCI OKE", "MSP tenant fleet", "cm_client_fleet_demo", "pending", "Install command not run"),
            ("MedLM Labs", "llm-prod", "GKE", "AI workloads", "cm_llm_prod_demo", "connected", "9 minutes ago"),
        ]
        for customer_name, cluster_name, provider, environment, token, status, last_seen in demo_clusters:
            if cluster_name not in existing and customer_name in customers:
                db.add(
                    ClusterConnection(
                        customer_id=customers[customer_name],
                        cluster_name=cluster_name,
                        provider=provider,
                        environment=environment,
                        token=token,
                        status=status,
                        last_seen=last_seen,
                    )
                )
        db.commit()
        return

    customers = [
        Customer(name="AstraPay Fintech", segment="SaaS", region="India", billing_model="Chargeback + AI usage"),
        Customer(name="NilaCloud MSP", segment="MSP", region="APAC", billing_model="Reseller billing"),
        Customer(name="MedLM Labs", segment="AI platform", region="Global", billing_model="Token + GPU metering"),
    ]
    db.add_all(customers)
    db.flush()

    c1, c2, c3 = [customer.id for customer in customers]
    db.add_all(
        [
            CloudSpend(customer_id=c1, provider="AWS", service="EKS + EC2", team="Dev", amount_inr=485000, month="2026-06"),
            CloudSpend(customer_id=c1, provider="GCP", service="BigQuery", team="Data", amount_inr=132000, month="2026-06"),
            CloudSpend(customer_id=c2, provider="OCI", service="OKE + Block Volume", team="Platform", amount_inr=221000, month="2026-06"),
            CloudSpend(customer_id=c2, provider="AWS", service="S3 + CloudFront", team="Customer Ops", amount_inr=98000, month="2026-06"),
            CloudSpend(customer_id=c3, provider="GCP", service="Vertex AI", team="ML", amount_inr=341000, month="2026-06"),
            CloudSpend(customer_id=c3, provider="OCI", service="GPU Compute", team="Research", amount_inr=286000, month="2026-06"),
        ]
    )

    db.add_all(
        [
            KubernetesCost(customer_id=c1, cluster="prod-mumbai", namespace="payments", workload="api-gateway", team="Dev", cpu_core_hours=8200, memory_gb_hours=28400, gpu_hours=0, amount_inr=120000, month="2026-06"),
            KubernetesCost(customer_id=c1, cluster="prod-mumbai", namespace="risk-engine", workload="fraud-scorer", team="ML", cpu_core_hours=5200, memory_gb_hours=18900, gpu_hours=38, amount_inr=178000, month="2026-06"),
            KubernetesCost(customer_id=c1, cluster="stage-mumbai", namespace="qa", workload="test-runners", team="QA", cpu_core_hours=2100, memory_gb_hours=8100, gpu_hours=0, amount_inr=50000, month="2026-06"),
            KubernetesCost(customer_id=c2, cluster="client-fleet-01", namespace="tenant-alpha", workload="erp-api", team="Managed Client A", cpu_core_hours=4400, memory_gb_hours=13900, gpu_hours=0, amount_inr=91000, month="2026-06"),
            KubernetesCost(customer_id=c2, cluster="client-fleet-01", namespace="tenant-beta", workload="analytics-worker", team="Managed Client B", cpu_core_hours=6100, memory_gb_hours=16700, gpu_hours=12, amount_inr=142000, month="2026-06"),
            KubernetesCost(customer_id=c3, cluster="llm-prod", namespace="rag", workload="embedder", team="AI Apps", cpu_core_hours=7600, memory_gb_hours=22400, gpu_hours=46, amount_inr=214000, month="2026-06"),
        ]
    )

    db.add_all(
        [
            AiUsage(customer_id=c1, provider="OpenAI", model="gpt-4.1", product="Support Copilot", tokens=88200000, requests=364000, gpu_seconds=0, storage_gb=240, documents=18400, amount_inr=267000, month="2026-06"),
            AiUsage(customer_id=c1, provider="Gemini", model="gemini-2.5-pro", product="Risk Review", tokens=41500000, requests=91000, gpu_seconds=0, storage_gb=94, documents=3700, amount_inr=139000, month="2026-06"),
            AiUsage(customer_id=c2, provider="Claude", model="claude-3.7-sonnet", product="Client Desk", tokens=63200000, requests=187000, gpu_seconds=0, storage_gb=160, documents=9300, amount_inr=203000, month="2026-06"),
            AiUsage(customer_id=c2, provider="Ollama", model="llama3.1:70b", product="Private RAG", tokens=27600000, requests=72000, gpu_seconds=188000, storage_gb=420, documents=21000, amount_inr=118000, month="2026-06"),
            AiUsage(customer_id=c3, provider="Mistral", model="large-latest", product="Clinical Drafting", tokens=95800000, requests=231000, gpu_seconds=0, storage_gb=310, documents=12700, amount_inr=301000, month="2026-06"),
            AiUsage(customer_id=c3, provider="OpenAI", model="o4-mini", product="Agent Runtime", tokens=121000000, requests=518000, gpu_seconds=0, storage_gb=128, documents=6400, amount_inr=354000, month="2026-06"),
        ]
    )

    db.add_all(
        [
            Invoice(customer_id=c1, invoice_no="CM-2026-0601", issue_date=date(2026, 6, 5), status="ready", cloud_amount_inr=617000, kubernetes_amount_inr=348000, ai_amount_inr=406000, tax_inr=246780, total_inr=1617780),
            Invoice(customer_id=c2, invoice_no="CM-2026-0602", issue_date=date(2026, 6, 5), status="draft", cloud_amount_inr=319000, kubernetes_amount_inr=233000, ai_amount_inr=321000, tax_inr=157140, total_inr=1030140),
            Invoice(customer_id=c3, invoice_no="CM-2026-0603", issue_date=date(2026, 6, 5), status="sent", cloud_amount_inr=627000, kubernetes_amount_inr=214000, ai_amount_inr=655000, tax_inr=269280, total_inr=1765280),
        ]
    )

    db.add_all(
        [
            BudgetAlert(customer_id=c1, scope="Namespace", owner="risk-engine", threshold_inr=150000, current_inr=178000, severity="high", message="GPU-backed fraud scoring crossed budget by 18.7%"),
            BudgetAlert(customer_id=c2, scope="Customer", owner="Managed Client B", threshold_inr=310000, current_inr=345000, severity="medium", message="MSP tenant needs revised monthly allocation"),
            BudgetAlert(customer_id=c3, scope="AI product", owner="Agent Runtime", threshold_inr=300000, current_inr=354000, severity="critical", message="OpenAI agent requests are trending 31% above plan"),
        ]
    )

    db.add_all(
        [
            ClusterConnection(customer_id=c1, cluster_name="prod-mumbai", provider="AWS EKS", environment="Production", token="cm_prod_mumbai_demo", status="connected", last_seen="2 minutes ago"),
            ClusterConnection(customer_id=c2, cluster_name="client-fleet-01", provider="OCI OKE", environment="MSP tenant fleet", token="cm_client_fleet_demo", status="pending", last_seen="Install command not run"),
            ClusterConnection(customer_id=c3, cluster_name="llm-prod", provider="GKE", environment="AI workloads", token="cm_llm_prod_demo", status="connected", last_seen="9 minutes ago"),
        ]
    )
    db.commit()
