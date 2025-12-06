"""
UCC (Uniform Commercial Code) Filings API Routes
=================================================

Dedicated API routes for UCC filings scraping and search.

Routes:
- GET /ucc/states - Get supported states and scrapability info
- GET /ucc/states/{state} - Get detailed info for a specific state
- POST /ucc/search - Search UCC filings for specific businesses
- POST /ucc/scan - Trigger a UCC scan for target states
"""

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from industry_deep_scan.api.main import get_engine, verify_api_key
from industry_deep_scan.engine import DeepScanEngine
from industry_deep_scan.models import SourceType
from industry_deep_scan.sources import (
    get_supported_states,
    get_scrapable_states,
    STATE_UCC_CONFIGS,
    UCCScrapability,
    ScrapingMethod,
)

router = APIRouter(prefix="/ucc", tags=["UCC Filings"])


# === Pydantic Models ===


class StateUCCInfo(BaseModel):
    """UCC state configuration information."""
    state_code: str
    state_name: str
    scrapability: str
    scrapability_rating: int = Field(description="Rating from 1-5, 5 being most scrapable")
    method: str
    requires_login: bool
    fee_required: bool
    notes: str
    is_available: bool = Field(description="Whether this state can be scraped without login/fees")


class StateListResponse(BaseModel):
    """Response with list of state configurations."""
    states: list[StateUCCInfo]
    total_states: int
    available_states: int
    scrapability_summary: dict


class UCCSearchRequest(BaseModel):
    """Request to search UCC filings."""
    business_names: list[str] = Field(
        ...,
        min_length=1,
        max_length=50,
        description="List of business names to search (max 50)"
    )
    states: Optional[list[str]] = Field(
        default=None,
        description="Target states (defaults to most scrapable states)"
    )


class UCCSearchResponse(BaseModel):
    """Response from UCC search."""
    status: str
    businesses_searched: int
    states_searched: list[str]
    signals_found: int
    results: list[dict]
    start_time: str
    end_time: str
    errors: list[str] = Field(default_factory=list)


class UCCScanRequest(BaseModel):
    """Request to trigger a UCC scan."""
    states: Optional[list[str]] = Field(
        default=None,
        description="Target states (defaults to available states)"
    )
    search_names: Optional[list[str]] = Field(
        default=None,
        description="Business names to search (required)"
    )


class UCCScanResponse(BaseModel):
    """Response from UCC scan."""
    status: str
    job_id: Optional[str] = None
    states_targeted: list[str]
    signals_found: int = 0
    errors: int = 0
    start_time: str
    end_time: Optional[str] = None
    details: dict = Field(default_factory=dict)


# === Helper Functions ===


def _get_scrapability_rating(scrapability: str) -> int:
    """Convert scrapability enum to numeric rating."""
    ratings = {
        UCCScrapability.EXCELLENT.value: 5,
        UCCScrapability.GOOD.value: 4,
        UCCScrapability.MODERATE.value: 3,
        UCCScrapability.DIFFICULT.value: 2,
        UCCScrapability.NOT_AVAILABLE.value: 1,
    }
    return ratings.get(scrapability, 1)


# === Routes ===


@router.get("/states", response_model=StateListResponse)
async def list_ucc_states(
    available_only: bool = Query(
        default=False,
        description="Only return states that can be scraped without login/fees"
    ),
    min_scrapability: Optional[int] = Query(
        default=None,
        ge=1,
        le=5,
        description="Minimum scrapability rating (1-5)"
    ),
    api_key: str = Depends(verify_api_key),
):
    """
    Get list of all supported states for UCC filing searches.

    Returns detailed information about each state's UCC system including:
    - Scrapability rating (1-5, with 5 being easiest to scrape)
    - Scraping method required (simple HTTP, Playwright, API)
    - Login/fee requirements
    - Notes and limitations

    Query Parameters:
    - available_only: Only return freely scrapable states
    - min_scrapability: Filter by minimum scrapability rating
    """
    all_states = get_supported_states()

    # Apply filters
    filtered_states = []
    for state in all_states:
        rating = _get_scrapability_rating(state["scrapability"])

        if available_only and not state["is_available"]:
            continue

        if min_scrapability and rating < min_scrapability:
            continue

        filtered_states.append(StateUCCInfo(
            state_code=state["state_code"],
            state_name=state["state_name"],
            scrapability=state["scrapability"],
            scrapability_rating=rating,
            method=state["method"],
            requires_login=state["requires_login"],
            fee_required=state["fee_required"],
            notes=state["notes"],
            is_available=state["is_available"],
        ))

    # Calculate summary
    scrapability_summary = {
        "excellent": sum(1 for s in all_states if s["scrapability"] == "excellent"),
        "good": sum(1 for s in all_states if s["scrapability"] == "good"),
        "moderate": sum(1 for s in all_states if s["scrapability"] == "moderate"),
        "difficult": sum(1 for s in all_states if s["scrapability"] == "difficult"),
        "unavailable": sum(1 for s in all_states if s["scrapability"] == "unavailable"),
    }

    available_count = sum(1 for s in all_states if s["is_available"])

    return StateListResponse(
        states=filtered_states,
        total_states=len(all_states),
        available_states=available_count,
        scrapability_summary=scrapability_summary,
    )


@router.get("/states/{state_code}", response_model=StateUCCInfo)
async def get_state_ucc_info(
    state_code: str,
    api_key: str = Depends(verify_api_key),
):
    """
    Get detailed UCC system information for a specific state.

    Path Parameters:
    - state_code: Two-letter state code (e.g., NY, CA, TX)
    """
    state_upper = state_code.upper()
    config = STATE_UCC_CONFIGS.get(state_upper)

    if not config:
        raise HTTPException(
            status_code=404,
            detail=f"State '{state_code}' not found. Use /ucc/states to see available states."
        )

    is_available = (
        config.method != ScrapingMethod.NOT_SUPPORTED
        and not config.requires_login
        and not config.fee_required
    )

    return StateUCCInfo(
        state_code=config.state_code,
        state_name=config.state_name,
        scrapability=config.scrapability.value,
        scrapability_rating=_get_scrapability_rating(config.scrapability.value),
        method=config.method.value,
        requires_login=config.requires_login,
        fee_required=config.fee_required,
        notes=config.notes,
        is_available=is_available,
    )


@router.get("/states/scrapable")
async def get_scrapable_state_list(
    api_key: str = Depends(verify_api_key),
):
    """
    Get a simple list of state codes that can be scraped without login or fees.

    Returns just the state codes - use /ucc/states for full details.
    """
    states = get_scrapable_states()
    return {
        "states": states,
        "count": len(states),
        "note": "These states can be scraped without login or payment requirements",
    }


@router.post("/search", response_model=UCCSearchResponse)
async def search_ucc_filings(
    request: UCCSearchRequest,
    api_key: str = Depends(verify_api_key),
    engine: DeepScanEngine = Depends(get_engine),
):
    """
    Search UCC filings for specific business names.

    Request Body:
    - business_names: List of business names to search (max 50)
    - states: Target states (defaults to most scrapable states)

    Returns:
    - Signals found for each business
    - State-by-state results
    - Any errors encountered
    """
    start_time = datetime.utcnow()

    # Validate states
    target_states = request.states or get_scrapable_states()[:5]

    invalid_states = []
    for state in target_states:
        if state.upper() not in STATE_UCC_CONFIGS:
            invalid_states.append(state)

    if invalid_states:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid state codes: {invalid_states}. Use /ucc/states to see available states."
        )

    results = []
    errors = []
    signals_found = 0

    try:
        # Get the UCC source
        ucc_source = engine.sources.get(SourceType.UCC_FILINGS)

        if not ucc_source:
            raise HTTPException(
                status_code=503,
                detail="UCC filings source not configured. Enable SOURCE_UCC_FILINGS_ENABLED=true"
            )

        # Perform search
        async for raw_signal, classification in engine.scan_source(
            SourceType.UCC_FILINGS,
            states=target_states,
            search_names=request.business_names,
        ):
            try:
                business, signal = await engine.process_signal(raw_signal, classification)

                if signal:
                    signals_found += 1
                    results.append({
                        "business_name": raw_signal.business_name,
                        "state": raw_signal.business_state,
                        "signal_type": signal.signal_type.value,
                        "priority": signal.priority.value,
                        "title": signal.title,
                        "description": signal.description,
                        "metadata": raw_signal.metadata,
                    })

            except Exception as e:
                errors.append(f"Error processing {raw_signal.business_name}: {str(e)}")

    except HTTPException:
        raise
    except Exception as e:
        errors.append(f"Search error: {str(e)}")

    end_time = datetime.utcnow()

    return UCCSearchResponse(
        status="completed" if not errors else "completed_with_errors",
        businesses_searched=len(request.business_names),
        states_searched=target_states,
        signals_found=signals_found,
        results=results,
        start_time=start_time.isoformat(),
        end_time=end_time.isoformat(),
        errors=errors,
    )


@router.post("/scan", response_model=UCCScanResponse)
async def trigger_ucc_scan(
    request: UCCScanRequest,
    api_key: str = Depends(verify_api_key),
    engine: DeepScanEngine = Depends(get_engine),
):
    """
    Trigger a UCC filings scan.

    Request Body:
    - states: Target states (defaults to available states)
    - search_names: Business names to search (required)

    This endpoint triggers a scan that:
    1. Searches UCC records in target states
    2. Identifies secured parties and MCA funders
    3. Detects stacking (multiple MCA positions)
    4. Creates signals for detected filings
    """
    start_time = datetime.utcnow()

    if not request.search_names:
        raise HTTPException(
            status_code=400,
            detail="search_names is required for UCC scans"
        )

    target_states = request.states or get_scrapable_states()

    try:
        result = await engine.run_source_scan(
            SourceType.UCC_FILINGS,
            states=target_states,
            search_names=request.search_names,
        )

        return UCCScanResponse(
            status="completed",
            states_targeted=target_states,
            signals_found=result.get("signals_found", 0),
            errors=result.get("errors", 0),
            start_time=start_time.isoformat(),
            end_time=datetime.utcnow().isoformat(),
            details=result,
        )

    except Exception as e:
        return UCCScanResponse(
            status="failed",
            states_targeted=target_states,
            start_time=start_time.isoformat(),
            end_time=datetime.utcnow().isoformat(),
            details={"error": str(e)},
        )


@router.get("/recommendations")
async def get_scraping_recommendations(
    api_key: str = Depends(verify_api_key),
):
    """
    Get recommendations for UCC scraping based on state scrapability analysis.

    Returns:
    - Recommended states to start with
    - States that require additional setup
    - States that cannot be scraped
    """
    all_states = get_supported_states()

    recommended = []
    needs_setup = []
    not_available = []

    for state in all_states:
        rating = _get_scrapability_rating(state["scrapability"])

        if state["is_available"] and rating >= 4:
            recommended.append({
                "state_code": state["state_code"],
                "state_name": state["state_name"],
                "scrapability_rating": rating,
                "notes": state["notes"],
            })
        elif state["is_available"] and rating >= 2:
            needs_setup.append({
                "state_code": state["state_code"],
                "state_name": state["state_name"],
                "scrapability_rating": rating,
                "method": state["method"],
                "notes": state["notes"],
                "recommendation": "May require Playwright for JavaScript rendering" if state["method"] == "playwright" else "Standard HTTP scraping",
            })
        else:
            not_available.append({
                "state_code": state["state_code"],
                "state_name": state["state_name"],
                "reason": state["notes"],
                "requires_login": state["requires_login"],
                "fee_required": state["fee_required"],
            })

    return {
        "recommended_states": recommended,
        "recommended_state_codes": [s["state_code"] for s in recommended],
        "needs_setup": needs_setup,
        "not_available": not_available,
        "summary": {
            "start_with": "New York (NY) has the cleanest, most reliable UCC search interface",
            "second_tier": "Arizona (AZ), North Carolina (NC) are good alternatives",
            "playwright_required": [s["state_code"] for s in needs_setup if s.get("method") == "playwright"],
            "total_available": len(recommended) + len(needs_setup),
            "total_unavailable": len(not_available),
        },
    }
