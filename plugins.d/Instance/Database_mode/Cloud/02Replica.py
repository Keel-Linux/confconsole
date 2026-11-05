"""Second node: the join, the pair, the copy"""

import meshscreen

TITLE = meshscreen.JOIN_TITLE
TEXT = (
    "The first boot's Replica flow (decision 0076): this node joins the"
    " mesh with the line the primary shows, writes the VIP the join"
    " received, pairs with the primary (keel vip pair), and then becomes"
    " a COPY of it: the database it holds now is REPLACED, and keel asks"
    " before it destroys anything. A step that is done already is not"
    " done again."
)


def run():
    meshscreen.from_menu(console, meshscreen.REPLICA)
