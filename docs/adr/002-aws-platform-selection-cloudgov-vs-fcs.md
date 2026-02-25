# ADR 0002: AWS Platform Selection for FDE Adapter Hosting (cloud.gov vs FCS Cloud)


## Status
Proposed


## Context
The FDE adapter is intended to be deployable in multiple agency environments and needs an AWS hosting approach that supports:


- Meeting required security/compliance needs (ATO/FedRAMP) for the target data.
- Network controls for cross-org communication over the public internet (typically HTTPS/443) including allowlisting constraints.
- Container-first deployment (portable to other environments over time).
- Operational support for running a small number of initial adapters and scaling to more deployments.
- A clear path for managing AWS accounts, IAM, secrets, logging, monitoring, and incident response.


We need to decide whether the default/primary AWS landing zone for GSA-hosted components (and any shared/control-plane components, as applicable) should be **cloud.gov (AWS)** or **FCS Cloud**.


## Decision Drivers
- Security/compliance fit (FedRAMP/ATO)
- Ease of getting to a first working environment (account setup, access, constraints)
- Supported compute model for the adapter (ECS/Fargate, EKS/Kubernetes, or equivalent)
- Network egress/ingress patterns and constraints (public endpoints, private connectivity needs)
- Security operations model (IAM patterns, key management, vulnerability management, patching responsibilities)
- Observability and operations (logs/metrics/traces, security logging/monitoring, runbooks, datadog/splunk/other)
- Costs and who pays for what (billing, tracking spend)
- Portability and repeatability (Terraform/GitOps, Jenkins, multi-environment promotion)


## Considered Options
### Option A: cloud.gov (AWS)
Use cloud.gov-managed AWS capabilities as the primary platform for hosting GSA-managed FDE components.


### Option B: FCS Cloud
Use FCS Cloud as the primary platform for hosting GSA-managed FDE components.


## Recommendation
Select **FCS Cloud** as the primary AWS platform for the FDE adapter hosting baseline.


Rationale:


- **Platform limits**: cloud.gov appears to have a narrower approved service set; FCS Cloud may offer more flexibility.
- **Getting started**: FCS Cloud may be faster/simpler to get accounts/access and deploy.
- **Networking**: FCS Cloud may better support our preferred inbound/outbound networking pattern for cross-org communication.
- **Security operations**: FCS Cloud may better align with our standard AWS security patterns (IAM/KMS/secrets) and security operations expectations.
- **Operations**: FCS Cloud may better support our preferred ops tooling (logging/monitoring) and standard AWS patterns.
- **Costs**: FCS Cloud may provide clearer billing/spend tracking for our team.
- **Portability**: FCS Cloud should work with Terraform/GitOps/Jenkins and multi-environment promotion.




## Follow-ups
- Confirm which components are GSA-hosted vs agency-hosted for the target architecture (control-plane vs data-plane responsibilities).
- Validate the constraints/assumptions with platform owners (cloud.gov and FCS) against the Decision Drivers.
- Update this ADR status to **Accepted** once stakeholders confirm the platform selection.


## References
- https://docs.cloud.gov/platform/technology/infrastructure-overview/
