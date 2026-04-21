# User Journeys

## Pull Request  

Able is at agency A and has some data. Betty is at agency B and wants that data. A and B sign an Information Sharing Agreement (ISA)
and then [TODO] that agreement gets recorded in the policy server. It links private key information connected to agency A with 
private key information connected to Agency B.

Able works with Agency A IT staff to run the adapter code inside of Agency A. Betty already has the adapter running at agency B.

Able configures the adapter to make some data available, e.g. gets an S3 bucket, puts data files in there and then sets up the adapter
at agency A to refer to that bucket. (Eventually, the adapter at agency A could have a UI for configuring multiple data
products that could be going to multiple different other agencies.) Agency A's configuration could express more details about
the fields available in the data.

When agency A's adapter restarts, it sends events to the FDE event server, expressing that it is making available certain data
products. The adapters all communicate back to the event server. You must come back to GSA to access the central policy server,
so we can also put an event server there that can be used to enable flexibility and control (logging, auditing, control, etc.)
If something breaks, it should fail-safe, auto shut-off.

(Fredo at FDE can log in to the FDE UI and can construct from events published to these topics a list of all of the products that
are available from Agency A.)

Betty is at Agency B logs into the FDE UI. My user is associated with agency B and so Betty finds a list of the data products
that are available to agency B. In the UI, Betty fills out a request for information from one of Agency A's data products. Betty
might provide parameters in that request such as matching names or ID numbers or time ranges. That request gets checked against
policy server and sent on to the event server as an event that B is requesting that data from A.

The A adapter sees that event request and checks the policy server that it is allowed and retrieves the data that matches the 
parameters. The A adapter is now sitting on the pile of data that matches that request. The A adapter checks the policy server
again that it is allowed to serve the data request and if it is, it posts an event to a topic that the data B requested is
ready.

[TODO] Figure out how A's adapter gets the data to B's adapter. The current situation is that agency B has to run an SFTP server
connected to an S3 bucket that B's adapter has access to.

B sees the data come into the bucket and posts an event that the data was received.


## Push Request  

Able is at agency A and collects data to be sent to Betty at agency B. Betty does not know when the data will be collected and sent,
but is aware that data can arrive and knows what to do with it. A and B sign an Information Sharing Agreement (ISA)
and then [TODO] that agreement gets recorded in the policy server. It links private key information connected to agency A with 
private key information connected to Agency B.

Able configures the adapter to make data available (on an IDIQ basis, or "continuous-push"), e.g. gets an S3 bucket and then sets 
up the adapter at agency A to monitor that bucket. (Eventually, the adapter at agency A could have a UI for configuring multiple 
data products that could be going to multiple different other agencies.) Agency A's configuration could express more details about
the fields available in the data.

When agency A's adapter restarts, it sends events to the FDE event server, expressing that it is making available certain data
products. The adapters all communicate back to the event server. You must come back to GSA to access the central policy server,
so we can also put an event server there that can be used to enable flexibility and control (logging, auditing, control, etc.)
If something breaks, it should fail-safe, auto shut-off.

(Fredo at FDE can log in to the FDE UI and can construct from events published to these topics a list of all of the products that
are available from Agency A.)

Able at Agency A logs into the FDE UI. My user is associated with Agency A and so Able finds a list of the continuous-push data products
that are available from agency A. In the UI, Able fills out a continuous-push request for information from one of Agency A's data 
products to be sent to Agency B.  That request gets checked against policy server and sent on to the event server as an event that A 
is requesting a continuous data push to B.

The A adapter sees that event request, checks the policy server that it is allowed and begins moniotoring for new data that matches 
the parameters. The A adapter is now sitting on the pile of data that matches that request. The A adapter checks the policy server
again that it is allowed to serve the data request and if it is, it posts an event to a topic that the data B will receive is
ready.

[TODO] Figure out how A's adapter gets the data to B's adapter. The current situation is that agency B has to run an SFTP server
connected to an S3 bucket that B's adapter has access to.

B sees the data come into the bucket and posts an event that the data was received. [TODO] A notification is automatically generated to 
alert receiver to new data.

