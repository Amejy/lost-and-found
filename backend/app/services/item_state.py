from backend.app.models.item import ItemStatus


ACTIVE_ITEM_STATUSES = (
    ItemStatus.OPEN,
    ItemStatus.MATCHED,
    ItemStatus.CLAIMED,
    ItemStatus.RESOLVED,
)

MATCHABLE_ITEM_STATUSES = (
    ItemStatus.OPEN,
    ItemStatus.MATCHED,
    ItemStatus.CLAIMED,
)

CLAIMABLE_FOUND_STATUSES = (
    ItemStatus.OPEN,
    ItemStatus.MATCHED,
    ItemStatus.CLAIMED,
)

CLAIM_LINKABLE_LOST_STATUSES = (
    ItemStatus.OPEN,
    ItemStatus.MATCHED,
    ItemStatus.CLAIMED,
)

EDITABLE_ITEM_STATUSES = (
    ItemStatus.OPEN,
    ItemStatus.MATCHED,
    ItemStatus.CLAIMED,
)


def is_active_item_status(status):
    return status in ACTIVE_ITEM_STATUSES


def is_claimable_found_status(status):
    return status in CLAIMABLE_FOUND_STATUSES


def is_matchable_item_status(status):
    return status in MATCHABLE_ITEM_STATUSES


def is_claim_linkable_lost_status(status):
    return status in CLAIM_LINKABLE_LOST_STATUSES


def is_editable_item_status(status):
    return status in EDITABLE_ITEM_STATUSES
