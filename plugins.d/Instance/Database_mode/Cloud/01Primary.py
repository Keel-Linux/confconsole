"""First node: the mesh, the invites, the VIP"""

import meshscreen

TITLE = meshscreen.INVITE_TITLE
TEXT = (
    "The first boot's Primary flow (decision 0076): this node makes the"
    " mesh when it has none, invites the replica (and in cloud advanced"
    " the witness) with a line you copy, writes the VIP the invite"
    " carries, and takes the VIP once the replica has paired. A step that"
    " is done already is not done again."
)


def run():
    meshscreen.from_menu(console, meshscreen.PRIMARY)
