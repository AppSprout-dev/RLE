"""Felix multi-agent harness (optional extra ``felix``).

Importing this package must stay cheap and Felix-free: the ``felix`` entry
point resolves to :data:`PLUGIN`, whose methods import the SDK-dependent
modules (``harness``, ``build``, ``provider_factory``) only when a Felix
harness is actually requested.
"""

from rle.harness.felix.plugin import PLUGIN, FelixPlugin

__all__ = ["PLUGIN", "FelixPlugin"]
