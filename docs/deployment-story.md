# Deployment Story  

```
1. Deploy Adapters at Agencies  
   i. cert generation   
   ii. FW policy updated  
   iii. config file creation/updates  
   iv. Adapter posts data products to event topic  

2. Policy processing   
   i. Policy-as-Code (PaC) service pulls data product post from topic  
   ii. Iterative process to extract data products  
   iii. Products compared to existing for that Agency  
       a. if new product, config read in and data owner contacted through login.gov for authorization  
       b. if product removed, data product listing in data libraryis set to hidden for cleanup processes  
       c. Once authorization is received, new data product "signed" and added to data library  

3. User Interface  
   i. User logs into portal, using login.gov authentication  
   ii. UI pulls available data products from data library based on Agency affiliation  
   iii. User submits send/receive request for availabe data product  
   iv. request is posted in topic on event service  

4. Event Service Orchestration  
   i. Request is forwarded to PaC to validate against signed data product: Data Product, Sending Agency, Receiving Agency  
   ii. T/F returned by PaC with restrictions (i.e. hours of operation, record limits, FISMA level, etc)  
   iii. PaC response posted to sending agency topic to be consumed by the agency's adapter  

5. Sending Adapter  
   i. received data request through subscribed topic  
   ii. lookup of data product and generates API/SQL string  
   iii. Using event services, posts to PaC topic to verify the string complies with signed policy: Data Product, Query String, Requesting Agency  
   iv. Response from PaC posted to sending adapter topic  
   v. If T, query is performed and data collected/encrypted  
   vi. Once data is collected, message is posted to event server to alert receiving adapter  

6. Receiving adapter  
   i. received data request through subscribed topic  
   ii. Receiving adapter checks with PaC to verify authority to receive data: Data Product, Sending Agency, Receiving Agency, Adapter's deployed FISMA environment  
   iii. If T, receiver replies with criteria for delivery: IP/DNS and/or other parameters to facilitate connectivity  
   iv. Reply is posted to sender topic for processing and implementation    
   v. Receiver signals receipt of data to event service   
   ```
   
