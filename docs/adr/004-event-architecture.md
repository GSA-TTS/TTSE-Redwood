---
# These are optional metadata elements. Feel free to remove any of them.
status: "proposed"
date: 2026-04-27
---

# Event-based architecture

## Context and Problem Statement

The FDE adapter needs to run in agency networks and perform a
number of actions depending on the asynchronous actions of other
adapters. To ease the compliance burden, we do not want to run a
persistent server that accepts incoming requests. In addition,
in the face of uncertainty, we want to have a place to impose
policy and constraints, such as pausing an agency's adapter.

## Considered Options

* Event-based architecture
* Manual configuration

## Decision Outcome

Chosen option: "Event-based architecture", because we need adapters
to be able to respond to changes outside of themselves.

### Consequences

* Good, because adapter can respond to events that occur outside of
  its running environment, such as data becoming available from
  a partner agency.
* Good, because the event server can be configured to handle events
  that are posted in a way that allows control from a central
  location. For example, we could stop accepting events sent 
  from a specific adapter.
* Bad, because we have to maintain a robust and reliable event
  server and make sure that it is accessible to the adapters running
  in all sending and receiving agencies
* Bad, because adapters need more complex logic for reading
  event topics and discerning what actions they need to take
  as a result.

## More Information

A manually configured adapter could be directed by agency staff to
perform a particular function in its configuration, but coordinating
between multiple agencies to do actions in order (for example, making
new data available and then picking up the new data) would be extremely
complicated.
