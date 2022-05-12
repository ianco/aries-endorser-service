import logging

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update

from api.core.config import settings
from api.endpoints.models.endorse import EndorseTransactionState, EndorseTransaction, txn_to_db_object
from api.db.models.endorse_request import EndorseRequest
from api.db.errors import DoesNotExist

import api.acapy_utils as au


logger = logging.getLogger(__name__)


async def get_endorser_did() -> str:
    diddoc = await au.acapy_GET("wallet/did/public")
    did = diddoc["result"]["did"]
    return did


async def db_add_db_txn_record(db: AsyncSession, db_txn: EndorseRequest):
    db.add(db_txn)
    await db.commit()


async def db_fetch_db_txn_record(db: AsyncSession, transaction_id: str) -> EndorseRequest:
    q = (
        select(EndorseRequest)
        .where(EndorseRequest.transaction_id == transaction_id)
    )
    result = await db.execute(q)
    result_rec = result.scalar_one_or_none()
    if not result_rec:
        raise DoesNotExist(
            f"{EndorseRequest.__name__}<transaction_id:{transaction_id}> does not exist"
        )
    db_txn: EndorseRequest = EndorseRequest.from_orm(result_rec)
    return db_txn


async def db_update_db_txn_record(db: AsyncSession, db_txn: EndorseRequest) -> EndorseRequest:
    payload_dict = db_txn.dict()
    q = (
        update(EndorseRequest)
        .where(EndorseRequest.endorse_request_id == db_txn.endorse_request_id)
        .where(EndorseRequest.transaction_id == db_txn.transaction_id)
        .values(payload_dict)
    )
    await db.execute(q)
    await db.commit()
    return await db_fetch_db_txn_record(db, db_txn.transaction_id)


async def store_endorser_request(db: AsyncSession, txn: EndorseTransaction):
    logger.info(f">>> called store_endorser_request with: {txn.transaction_id}")

    db_txn: EndorseRequest = txn_to_db_object(txn)
    await db_add_db_txn_record(db, db_txn)
    logger.info(f">>> stored endorser_request: {db_txn.transaction_id}")

    return txn


async def endorse_transaction(db: AsyncSession, txn: EndorseTransaction):
    logger.info(f">>> called endorse_transaction with: {txn.transaction_id}")

    # fetch existing db object
    db_txn: EndorseRequest = await db_fetch_db_txn_record(db, txn.transaction_id)

    # endorse transaction and tell aca-py
    await au.acapy_POST(f"transactions/{txn.transaction_id}/endorse")

    # update local db status
    db_txn = await db_update_db_txn_record(db, db_txn)
    logger.info(f">>> updated endorser_request for {txn.transaction_id}")

    return txn


async def update_endorsement_status(db: AsyncSession, txn: EndorseTransaction):
    logger.info(f">>> called update_endorsement_status with: {txn.transaction_id}")

    # fetch existing db object
    db_txn: EndorseRequest = await db_fetch_db_txn_record(db, txn.transaction_id)

    # update state from webhook
    db_txn.state = txn.state

    # update local db status
    db_txn = await db_update_db_txn_record(db, db_txn)
    logger.info(f">>> updated endorser_request for {txn.transaction_id} {txn.state}")

    return txn