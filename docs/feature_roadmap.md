
**Development schedule**

*   Agent
    *   Event Management
        *   Broker connectivity
        *   Authentication & Security
        *   Topic Subscription
        *   Agent Role
    *   Policy Connector
        *   Request validation
        *   Parameter enforcement (special handling instructions)
    *   Point-to-point data transfer
        *   Trigger event
        *   Policy checker
        *   Encrypted in transit
        *   Audit


*   Policy Server
    *   Requirements (what must the policy server do, take into consideration)
    *   Policy definitions (what defines an acquisition transfer, a tax return transfer)
    *   Data transformation (making data fit an enforceable policy)
    *   Parameter enforcement (source and destination endpoints, encryption levels, storage requirements, labeling)
*   Central Event Server
    *   Validation (Policy + authorization)
    *   Task assignment (input topics)
    *   Task verification (output topics)
    *   Workflow definition (orchestration)
    *   Agent Roles
    *   Subscriptions vs one-time transfers
*   Encryption (PKI Server)
    *   Session keys
    *   Token store
*   User Interface
    *   Request Portal (-> Event Server)
    *   Policy Definition (-> Policy Server)
    *   Audit (<- Event Server)
