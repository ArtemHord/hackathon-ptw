# Postmortem INC-011 - NovaStore (synthetic)
Owner: Kamil (Incident Lead). Date: 2026-08-18. Status: closed.

## Observed impact
All test checkout attempts failed; promotional prices were incorrect. In this fictional story no real loss amount is assigned.

## Hypotheses investigated
1. Payment gateway outage - not confirmed by the provider status.
2. Wrong discount - the discount alone did not explain the payment failure.
3. CRM Bridge / Salesforce - auth_failure and access token expired confirmed; on staging, isolating the plugin restored prices and checkout.

## Confirmed root cause
Expired Salesforce API access token in the CRM Bridge integration. The failure of this integration showed up in prices and checkout.

## Mitigation and closure
With the Incident Lead's approval the faulty integration was temporarily disabled, a checkout test was run, then the authorization was renewed, CRM sync restored and both processes verified.

## Expert
Ola - Salesforce/WooCommerce integrations. Reference: meeting INC-011, 14:08-15:05.

## Lesson
A payment failure does not have to mean a gateway failure. When prices are also wrong, check plugin dependencies and integration logs.
