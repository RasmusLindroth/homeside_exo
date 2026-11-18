"""Konstanter för HomeSide EXO-integrationen."""

DOMAIN = "homeside_exo"

CONF_HOST = "host"
CONF_USER = "user"
CONF_PASSWORD = "password"
CONF_SCAN_INTERVAL = "scan_interval"
CONF_TEMPLATE = "template"

# Regulatormallar som points.json är verifierad mot. Indexen (t.ex. 96 = rum 1
# temperatur) gäller per mall – en annan mall kan ge fel värden.
SUPPORTED_TEMPLATES = {"MALL_FJV_Villa_2_244"}

DEFAULT_SCAN_INTERVAL = 60  # sekunder
MIN_SCAN_INTERVAL = 15

# En login-skyddad punkt som används för att validera inloggningen i config-flow
# (rum 1 temperatur). Ger "Access denied" vid fel lösenord.
AUTH_CHECK_ITEM = 96
