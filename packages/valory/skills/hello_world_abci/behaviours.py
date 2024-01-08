# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2021-2023 Valory AG
#
#   Licensed under the Apache License, Version 2.0 (the "License");
#   you may not use this file except in compliance with the License.
#   You may obtain a copy of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
#   Unless required by applicable law or agreed to in writing, software
#   distributed under the License is distributed on an "AS IS" BASIS,
#   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#   See the License for the specific language governing permissions and
#   limitations under the License.
#
# ------------------------------------------------------------------------------

"""This module contains the behaviours for the 'hello_world' skill."""

import random
from abc import ABC
from typing import Generator, Set, Type, cast
from packages.valory.protocols.contract_api import ContractApiMessage

from packages.valory.skills.abstract_round_abci.behaviours import (
    AbstractRoundBehaviour,
    BaseBehaviour,
)
from packages.valory.skills.hello_world_abci.models import HelloWorldParams, SharedState
from packages.valory.skills.hello_world_abci.payloads import (
    CollectRandomnessPayload,
    NFTTransferPayload,
    RegistrationPayload,
    ResetPayload,
    SelectKeeperPayload,
)
from packages.valory.skills.hello_world_abci.rounds import (
    CollectRandomnessRound,
    HelloWorldAbciApp,
    NFTTransferRound,
    RegistrationRound,
    ResetAndPauseRound,
    SelectKeeperRound,
    SynchronizedData,
)


class HelloWorldABCIBaseBehaviour(BaseBehaviour, ABC):
    """Base behaviour behaviour for the Hello World abci skill."""

    @property
    def synchronized_data(self) -> SynchronizedData:
        """Return the synchronized data."""
        return cast(
            SynchronizedData, cast(SharedState, self.context.state).synchronized_data
        )

    @property
    def params(self) -> HelloWorldParams:
        """Return the params."""
        return cast(HelloWorldParams, self.context.params)


class RegistrationBehaviour(HelloWorldABCIBaseBehaviour):
    """Register to the next round and check NFT ownership."""

    matching_round = RegistrationRound

    async def async_act(self):
        """Perform async action to check NFT ownership and register agents."""
        # Check if the agent is the NFT owner and build the registration payload
        registration_payload = RegistrationPayload(self.context.agent_address)
        nft_owner_payload = None  # This will store the NFT owner payload if the agent owns the NFT
        
        # Fetch the current NFT owner from the smart contract
        current_nft_owner = await self.get_nft_owner()
        
        if current_nft_owner:
            self.context.logger.info(f"NFT (Token ID: {self.token_id}) is currently owned by {current_nft_owner}.")
            if current_nft_owner == self.context.agent_address:
                nft_owner_payload = RegistrationPayload(self.context.agent_address, is_nft_owner=True)

        # Send the registration payload
        await self.send_a2a_transaction(registration_payload)

        # Additionally send the NFT owner payload if it exists
        if nft_owner_payload:
            await self.send_a2a_transaction(nft_owner_payload)

        # Wait until the end of the round
        await self.wait_until_round_end()
        self.set_done()

class CollectRandomnessBehaviour(HelloWorldABCIBaseBehaviour):
    """Retrieve randomness."""

    matching_round = CollectRandomnessRound

    def async_act(self) -> Generator:
        """
        Check whether tendermint is running or not.

        Steps:
        - Do a http request to the tendermint health check endpoint
        - Retry until healthcheck passes or timeout is hit.
        - If healthcheck passes set done event.
        """
        if self.context.randomness_api.is_retries_exceeded():
            # now we need to wait and see if the other agents progress the round
            yield from self.wait_until_round_end()
            self.set_done()
            return

        api_specs = self.context.randomness_api.get_spec()
        http_message, http_dialogue = self._build_http_request_message(
            method=api_specs["method"],
            url=api_specs["url"],
        )
        response = yield from self._do_request(http_message, http_dialogue)
        observation = self.context.randomness_api.process_response(response)

        if observation:
            self.context.logger.info(f"Retrieved DRAND values: {observation}.")
            payload = CollectRandomnessPayload(
                self.context.agent_address,
                observation["round"],
                observation["randomness"],
            )
            yield from self.send_a2a_transaction(payload)
            yield from self.wait_until_round_end()
            self.set_done()
        else:
            self.context.logger.error(
                f"Could not get randomness from {self.context.randomness_api.api_id}"
            )
            yield from self.sleep(self.params.sleep_time)
            self.context.randomness_api.increment_retries()

    def clean_up(self) -> None:
        """
        Clean up the resources due to a 'stop' event.

        It can be optionally implemented by the concrete classes.
        """
        self.context.randomness_api.reset_retries()


class SelectKeeperBehaviour(HelloWorldABCIBaseBehaviour, ABC):
    """Select the keeper agent."""

    matching_round = SelectKeeperRound

    def async_act(self) -> Generator:
        """
        Do the action.

        Steps:
        - Select a keeper randomly.
        - Send the transaction with the keeper and wait for it to be mined.
        - Wait until ABCI application transitions to the next round.
        - Go to the next behaviour (set done event).
        """

        participants = sorted(self.synchronized_data.participants)
        random.seed(self.synchronized_data.most_voted_randomness, 2)  # nosec
        index = random.randint(0, len(participants) - 1)  # nosec

        keeper_address = participants[index]

        self.context.logger.info(f"Selected a new keeper: {keeper_address}.")
        payload = SelectKeeperPayload(self.context.agent_address, keeper_address)

        yield from self.send_a2a_transaction(payload)
        yield from self.wait_until_round_end()

        self.set_done()



class NFTTransferBehaviour(HelloWorldABCIBaseBehaviour):
    """Behaviour for handling the NFT transfer."""

    matching_round = NFTTransferRound
    
    async def async_act(self) -> Generator:
        """
        Perform the NFT transfer.
        """
        # Retrieve the most voted keeper address and NFT ownership information from the synchronized data
        most_voted_keeper_address = self.synchronized_data.most_voted_keeper_address
        current_owner_address = self.synchronized_data.get_nft_owner_by_token_id(self.context.params.token_id)
        
        if most_voted_keeper_address and self.context.agent_address == current_owner_address:
            # Interaction with the Ethereum API or other blockchain service
            self.ledger_api = self.context.ledger_apis.get_api('ethereum')

            # Fetch contract and token id details from context parameters
            contract_id = self.context.params.contract_id
            token_id = self.context.params.token_id
            
            # Fetch the contract instance
            nft_contract = self.ledger_api.get_contract(contract_id)
            transfer_function = nft_contract.functions.transferFrom(current_owner_address, most_voted_keeper_address, token_id)

            # Create the transaction to transfer the NFT
            tx = transfer_function.build_transaction({
                "from": current_owner_address  # This sends the transaction from the current owner's address
            })

            # The following steps assume the agent's private key is loaded and accessible for signing transactions
            # Sign the transaction
            tx_signed = self.ledger_api.sign_transaction(tx)
            
            # Send the signed transaction
            tx_digest = self.ledger_api.send_signed_transaction(tx_signed)

            if tx_digest:
                self.context.logger.info(f"Transaction successfully sent with digest: {tx_digest}")
                # Broadcast a payload to notify other agents of the NFT transfer (assuming this function exists)
                nft_transfer_payload = ... # Create the payload to notify others
                await self.send_a2a_transaction(nft_transfer_payload)
            else:
                self.context.logger.error("Failed to send the NFT transfer transaction.")

            # Proceed to the next round or behave according to the transaction result
            self.set_done()
        elif most_voted_keeper_address:
            # The current agent is not the owner, so no action is required
            self.set_done()
        else:
            self.context.logger.error("No agent elected to receive the NFT; transfer cannot proceed.")
            self.set_failed()

class ResetAndPauseBehaviour(HelloWorldABCIBaseBehaviour):
    """Reset behaviour."""

    matching_round = ResetAndPauseRound
    pause = True

    def async_act(self) -> Generator:
        """
        Do the action.

        Steps:
        - Trivially log the behaviour.
        - Sleep for configured interval.
        - Build a registration transaction.
        - Send the transaction and wait for it to be mined.
        - Wait until ABCI application transitions to the next round.
        - Go to the next behaviour (set done event).
        """
        if self.pause:
            self.context.logger.info("Period end.")
            yield from self.sleep(self.params.reset_pause_duration)
        else:
            self.context.logger.info(
                f"Period {self.synchronized_data.period_count} was not finished. Resetting!"
            )

        payload = ResetPayload(
            self.context.agent_address, self.synchronized_data.period_count
        )

        yield from self.send_a2a_transaction(payload)
        yield from self.wait_until_round_end()
        self.set_done()


class HelloWorldRoundBehaviour(AbstractRoundBehaviour):
    """This behaviour manages the consensus stages for the Hello World abci app."""

    initial_behaviour_cls = RegistrationBehaviour
    abci_app_cls = HelloWorldAbciApp
    behaviours: Set[Type[BaseBehaviour]] = {
        RegistrationBehaviour,  # type: ignore
        CollectRandomnessBehaviour,  # type: ignore
        SelectKeeperBehaviour,  # type: ignore
        NFTTransferBehaviour,  # type: ignore
        ResetAndPauseBehaviour,  # type: ignore
    }
