### Architecture Diagram: Controlled Data Sharing System

<img width="960" height="720" alt="Redwood System Architecture" src="https://github.com/user-attachments/assets/e43fe749-0d4d-421c-a814-b293236e5b2c" />


### Component Descriptions

1.  **User Portal (Web Interface):**
    *   **Purpose:** The primary interface for users to initiate data transfer requests.
    *   **Functions:** Accepts user input for data requests (e.g., source agency, target agency, data type, justification).
    *   **Interactions:** Communicates with the Policy Server for initial request validation and with the Event Server to submit validated requests for orchestration.

2.  **Policy Server (Access Control, Validation Rules):**
    *   **Purpose:** The central authority for enforcing data sharing policies and validating requests at various stages.
    *   **Functions:**
        *   **User Request Validation:** Checks if a user is authorized to make a specific request.
        *   **Agent Processing Validation:** Validates an agent's request to process data (e.g., ensuring the agent has permission to access the requested data).
        *   **Agent Sending Validation:** Validates an agent's intent to send data to another agent (e.g., ensuring the receiving agent is authorized to receive that specific data).
        *   **Policy Management:** Stores and manages all data sharing rules, access controls, and compliance requirements.
    *   **Interactions:** All components (User Portal, Agents) consult the Policy Server for validation checks.

3.  **Event Server (Orchestration, Audit Log):**
    *   **Purpose:** Manages the lifecycle of data transfer requests, orchestrates agent activities, and maintains a comprehensive audit trail.
    *   **Functions:**
        *   **Request Orchestration:** Receives validated requests from the User Portal, breaks them down into tasks, and dispatches commands to the appropriate Agents.
        *   **State Management:** Tracks the status of each data transfer request.
        *   **Audit Logging:** Records all significant events, including request submissions, validation outcomes, agent activities (data extraction, sending, receiving), errors, and completion statuses. This log serves as the official audit trail.
    *   **Interactions:** Receives requests from the User Portal, sends commands to Agents, and receives status updates from Agents.

4.  **Agents (Data Extractor & Sender / Data Receiver & Processor):**
    *   **Purpose:** Distributed components located at each agency responsible for executing data transfer tasks.
    *   **Functions:**
        *   **Data Extraction:** Connects to local agency data sources to extract requested data.
        *   **Data Sending:** Securely transmits extracted data to other authorized agents.
        *   **Data Receiving:** Securely receives data from other agents.
        *   **Data Processing (Optional):** May perform initial processing or validation of received data before storage.
        *   **Validation Check:** Consults the Policy Server before processing a request and before sending data.
    *   **Interactions:** Receive commands from the Event Server, consult the Policy Server for validation, and communicate directly with other agents for data transfer.

5.  **PKI Server (Certificates, Key Management):**
    *   **Purpose:** Provides the necessary infrastructure for secure communication across all components.
    *   **Functions:**
        *   **Certificate Authority (CA):** Issues digital certificates to all servers and agents in the system.
        *   **Key Management:** Manages cryptographic keys used for encryption and digital signatures.
        *   **Secure Channel Establishment:** Enables the establishment of secure communication channels (e.g., using TLS/SSL) for all interactions between components (User Portal, Policy Server, Event Server, Agents).
    *   **Interactions:** While not a direct transactional component in the data flow, all other servers and agents rely on the PKI Server to establish and maintain their secure communication links.

### Data Flow Explanation

Here's how a typical data transfer request would flow through the system:

1.  **User Initiates Request:** A user logs into the **User Portal** and submits a data transfer request.
2.  **Initial Policy Validation:** The **User Portal** sends the request details to the **Policy Server** for an initial validation. The Policy Server checks if the user is authorized to make this type of request, given the specified data, source, and destination.
3.  **Request Submission to Event Server:** If validated by the Policy Server, the **User Portal** submits the approved request to the **Event Server**.
4.  **Orchestration and Task Dispatch:** The **Event Server** logs the request (audit trail) and begins orchestrating the process. It identifies the source and destination agencies/agents involved.
5.  **Agent A (Source) Receives Command:** The **Event Server** dispatches a command to **Agent A** (at the source agency) to extract the specified data.
6.  **Agent A (Source) Pre-Processing Validation:** Before extracting data, **Agent A** consults the **Policy Server** to ensure it has the necessary permissions to access and extract that specific data.
7.  **Data Extraction:** If validated, **Agent A** extracts the data from its local systems.
8.  **Agent A (Source) Pre-Sending Validation:** Before sending the extracted data, **Agent A** again consults the **Policy Server** to ensure that the data can be sent to the intended **Agent B** (at the destination agency) according to policy.
9.  **Secure Data Transfer:** If validated, **Agent A** establishes a secure connection (using certificates provided by the **PKI Server**) with **Agent B** and securely transfers the data.
10. **Agent B (Destination) Pre-Receiving Validation:** Upon receiving the data, or even before fully processing it, **Agent B** might consult the **Policy Server** to confirm its authorization to receive and process this specific data from **Agent A**.
11. **Data Ingestion/Processing:** If validated, **Agent B** ingests or processes the received data into its local systems.
12. **Status Updates and Audit Trail:** Throughout this process, both **Agent A** and **Agent B** send status updates back to the **Event Server**, which meticulously logs every step, decision, and data transfer event, building a comprehensive audit trail.

All communications between these components are secured using cryptographic methods facilitated by the **PKI Server**, ensuring confidentiality, integrity, and authenticity of messages and data.

This architecture provides a robust framework for controlled data sharing, emphasizing policy enforcement, secure communication, and a clear audit trail.
