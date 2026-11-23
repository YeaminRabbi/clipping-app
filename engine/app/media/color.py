"""Turning HDR video (phones record it by default) into ordinary SDR colors."""

HDR_TRANSFERS = ("smpte2084", "arib-std-b67")  # PQ (HDR10) and HLG
# HDR puts ordinary white at 203 nits (ITU-R BT.2408). Up to 80% of that, colors are kept as they are;
# what's brighter is squeezed into the rest.
REFERENCE_WHITE_NITS = 203


def tone_map_filter(transfer: str | None) -> str:
    """Filters (without brackets, ending in none) from HDR to BT.709 SDR, or "" for ordinary video.

    Without this, HDR values end up in an 8-bit file and look gray and flat wherever HDR isn't understood.
    """
    if transfer not in HDR_TRANSFERS:
        return ""
    return (
        # Files don't always say all of this, and zscale refuses to guess.
        f"setparams=color_primaries=bt2020:color_trc={transfer}:colorspace=bt2020nc,"
        f"zscale=t=linear:npl={REFERENCE_WHITE_NITS},format=gbrpf32le,zscale=p=bt709,"
        "tonemap=tonemap=mobius:param=0.8:desat=0,zscale=t=bt709:m=bt709:r=tv,format=yuv420p"
    )
