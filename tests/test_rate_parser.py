"""Unit tests for LxmlRateParser. No network access.

The canned documents mirror a rate captured from a live Magaya install. A rate
inlines whole object graphs — the carrier's full entity record and the charge's
account — and those repeat the tag names the rate uses for its own fields. The
assertions here are mostly about keeping those apart:

    <Rate>            <Type>Standard</Type>
      <ChargeDefinition><Type>Freight</Type>   …
      <Carrier>        <Type>Carrier</Type><Name>…</Name>
      <PackageRates><PackageRate><Package><Type>Container</Type>

Four different `<Type>` values, one of which is the rate's own.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from magaya_toolkit.domain.errors import XmlValidationError
from magaya_toolkit.infrastructure.xml.rate_parser import LxmlRateParser

_NS = "http://www.magaya.com/XMLSchema/V1"

_RATE_BODY = """
  <Rate GUID="rate-guid-1">
    <Type>Standard</Type>
    <ChargeDefinition>
      <Type>Freight</Type>
      <Description>COORDINACION DE LOGISTICA TERRESTRE.</Description>
      <Code>5</Code>
      <AccountDefinition>
        <Type>Income</Type>
        <Name>INGRESOS</Name>
        <Number>401-000-000</Number>
        <Currency Code="USD"><Name>US Dollar</Name></Currency>
      </AccountDefinition>
      <Amount Currency="MXN">0.00</Amount>
      <Currency Code="MXN"><Name>Mexican Peso</Name></Currency>
    </ChargeDefinition>
    <Carrier GUID="carrier-guid-1">
      <Type>Carrier</Type>
      <Name>MAERSK  (HAMBURG)</Name>
      <Email>ops@example.test</Email>
      <Address><Country Code="DE">GERMANY</Country></Address>
    </Carrier>
    <Services>
      <Service>PortToPort</Service>
      <Service>DoorToDoor</Service>
    </Services>
    <OriginCountry Code="MX">MEXICO</OriginCountry>
    <DestinationCountry Code="US">UNITED STATES</DestinationCountry>
    <ApplicableModesOfTransportation>
      <AllMethodsIncluded>false</AllMethodsIncluded>
      <Methods><Method>Ground</Method></Methods>
      <ModesOfTransportation>
        <ModeOfTransportation Code="30">
          <Description>Terrestre Exportacion FTL</Description>
          <Method>Ground</Method>
        </ModeOfTransportation>
      </ModesOfTransportation>
    </ApplicableModesOfTransportation>
    <Currency Code="MXN"><Name>Mexican Peso</Name></Currency>
    <ApplyBy>Package</ApplyBy>
    <PackageRates>
      <PackageRate>
        <Package>
          <Type>Container</Type>
          <Code>CNT</Code>
          <Name>20 Ft. Contenedor</Name>
          <ContainerCode>2B</ContainerCode>
          <ContainerEquipType>22G0</ContainerEquipType>
          <Methods><Method>Ocean</Method><Method>Ground</Method></Methods>
        </Package>
        <Price Currency="MXN">50.00</Price>
      </PackageRate>
      <PackageRate>
        <Package><Type>Container</Type><Code>CNT40</Code></Package>
        <Price Currency="MXN">90.50</Price>
      </PackageRate>
    </PackageRates>
    <Frequency>Other</Frequency>
    <CreatedOn>2022-07-07T16:16:08-05:00</CreatedOn>
    <UseGrossWeight>false</UseGrossWeight>
    <IsHazardous>false</IsHazardous>
    <IsAutomaticCreateCharge>false</IsAutomaticCreateCharge>
  </Rate>
"""

_STANDARD_RATES = f"""<?xml version="1.0" encoding="utf-8"?>
<StandardRates xmlns="{_NS}">{_RATE_BODY}</StandardRates>"""

# A weight-priced rate: descriptive fields are there, but its prices live in an
# element this parser does not read.
_WEIGHT_RATE = f"""<?xml version="1.0" encoding="utf-8"?>
<ClientRates xmlns="{_NS}">
  <Rate GUID="rate-guid-2">
    <Type>Client</Type>
    <ApplyBy>Weight</ApplyBy>
    <OriginCountry Code="MX">MEXICO</OriginCountry>
    <WeightRates><WeightRate><Price Currency="MXN">7.25</Price></WeightRate></WeightRates>
  </Rate>
</ClientRates>"""


@pytest.fixture
def parser() -> LxmlRateParser:
    return LxmlRateParser()


# -- the rate's own fields vs the graphs it inlines ------------------------


def test_inlined_graphs_do_not_shadow_the_rates_own_fields(
    parser: LxmlRateParser,
) -> None:
    (rate,) = parser.parse(_STANDARD_RATES)

    # <Type> exists on the rate, the charge, the carrier AND the package.
    assert rate.type == "Standard"
    assert rate.guid == "rate-guid-1"
    # <Currency> exists on the rate, the charge and the charge's account.
    assert rate.currency is not None and rate.currency.code == "MXN"


def test_reuses_the_catalog_charge_definition_model(parser: LxmlRateParser) -> None:
    (rate,) = parser.parse(_STANDARD_RATES)

    assert rate.charge_definition is not None
    assert rate.charge_definition.type == "Freight"
    assert rate.charge_definition.code == "5"
    assert rate.charge_definition.account_definition is not None
    assert rate.charge_definition.account_definition.number == "401-000-000"
    # The account keeps its OWN currency, not the charge's.
    assert rate.charge_definition.account_definition.currency is not None
    assert rate.charge_definition.account_definition.currency.code == "USD"


def test_carrier_is_reduced_to_a_pointer_not_a_full_entity(
    parser: LxmlRateParser,
) -> None:
    """Magaya inlines the whole carrier record; we keep only the pointer."""
    (rate,) = parser.parse(_STANDARD_RATES)

    assert rate.carrier is not None
    assert rate.carrier.guid == "carrier-guid-1"
    assert rate.carrier.name == "MAERSK  (HAMBURG)"
    assert rate.carrier.type == "Carrier"
    assert not hasattr(rate.carrier, "email")


# -- lane, modes and services ---------------------------------------------


def test_parses_lane_countries_from_text_and_code_attribute(
    parser: LxmlRateParser,
) -> None:
    (rate,) = parser.parse(_STANDARD_RATES)

    assert rate.origin_country == "MEXICO"
    assert rate.origin_country_code == "MX"
    assert rate.destination_country == "UNITED STATES"
    assert rate.destination_country_code == "US"


def test_collects_repeated_services(parser: LxmlRateParser) -> None:
    (rate,) = parser.parse(_STANDARD_RATES)

    assert rate.services == ["PortToPort", "DoorToDoor"]


def test_parses_applicable_modes_with_configured_modes(parser: LxmlRateParser) -> None:
    (rate,) = parser.parse(_STANDARD_RATES)

    modes = rate.applicable_modes
    assert modes is not None
    assert modes.all_methods_included is False
    assert modes.methods == ["Ground"]
    assert len(modes.modes) == 1
    assert modes.modes[0].code == "30"
    assert modes.modes[0].description == "Terrestre Exportacion FTL"
    assert modes.modes[0].method == "Ground"


# -- pricing ---------------------------------------------------------------


def test_parses_every_package_rate_with_its_price_and_currency(
    parser: LxmlRateParser,
) -> None:
    (rate,) = parser.parse(_STANDARD_RATES)

    assert rate.apply_by == "Package"
    assert len(rate.package_rates) == 2

    first = rate.package_rates[0]
    assert first.package is not None
    assert first.package.code == "CNT"
    assert first.package.container_code == "2B"
    assert first.package.container_equip_type == "22G0"
    assert first.package.methods == ["Ocean", "Ground"]
    assert first.price is not None
    assert first.price.value == Decimal("50.00")
    assert first.price.unit == "MXN"

    assert rate.package_rates[1].price is not None
    assert rate.package_rates[1].price.value == Decimal("90.50")


def test_prices_helper_flattens_every_price(parser: LxmlRateParser) -> None:
    (rate,) = parser.parse(_STANDARD_RATES)

    assert rate.prices == [Decimal("50.00"), Decimal("90.50")]


def test_a_non_package_rate_parses_with_no_package_prices(
    parser: LxmlRateParser,
) -> None:
    """Only Package pricing is parsed; other `apply_by` values still describe."""
    (rate,) = parser.parse(_WEIGHT_RATE)

    assert rate.apply_by == "Weight"
    assert rate.type == "Client"
    assert rate.origin_country_code == "MX"
    assert rate.package_rates == []
    assert rate.prices == []


# -- the three document roots ----------------------------------------------


@pytest.mark.parametrize("root", ["StandardRates", "ClientRates", "CarrierRates"])
def test_accepts_each_of_the_three_rate_document_roots(
    parser: LxmlRateParser, root: str
) -> None:
    doc = f'<?xml version="1.0" encoding="utf-8"?><{root} xmlns="{_NS}">{_RATE_BODY}</{root}>'

    (rate,) = parser.parse(doc)

    assert rate.guid == "rate-guid-1"


def test_an_empty_rate_document_is_an_empty_list(parser: LxmlRateParser) -> None:
    assert parser.parse(f'<CarrierRates xmlns="{_NS}"/>') == []


def test_rejects_a_document_with_an_unrelated_root(parser: LxmlRateParser) -> None:
    with pytest.raises(XmlValidationError):
        parser.parse(f'<Currencies xmlns="{_NS}"/>')


def test_rejects_malformed_xml(parser: LxmlRateParser) -> None:
    with pytest.raises(XmlValidationError):
        parser.parse("<StandardRates><Rate>")
