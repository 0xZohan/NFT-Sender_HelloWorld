# Hello World abci

## Description

This module contains the ABCI Hello World skill for an AEA. It implements an ABCI
application for a simple demonstration.

## Behaviours

* `HelloWorldABCIBaseState`

   Base state behaviour for the Hello World abci skill.

* `RegistrationBehaviour`

   Register to the next round.

* `SelectKeeperBehaviour`

   Select the keeper agent.

* `NFTTransferBehaviour`

   Transfers the NFT to the agent with the most votes.

* `ResetAndPauseBehaviour`

   Reset state.

## Handlers

* `HelloWorldABCIHandler`
* `HttpHandler`
* `SigningHandler`
