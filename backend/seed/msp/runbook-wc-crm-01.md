# RUNBOOK-WC-CRM-01 - Checkout fails + wrong prices
Owner: Ola | Applies to: NovaStore | Related incident: INC-011 (synthetic).

1. Confirm the impact: does every payment fail, are prices incorrect; note the time and sample tests.
2. Check the payment gateway status, but do not assume the problem comes from the gateway.
3. Review the WooCommerce / WordPress / CRM Bridge logs; look for auth_failure, token expired and sync errors. Do not copy tokens into transcripts or Slack.
4. Assess the dependencies between CRM Bridge and the cart/prices. Reproduce in the staging environment if possible.
5. If isolating the integration restores checkout, present the Incident Lead with the risk of losing CRM sync temporarily and get approval for the mitigation.
6. After approval, an authorized engineer performs the temporary mitigation; confirm the checkout test and price consistency.
7. Re-create the CRM authorization following the security procedure, restore the integration and verify the sync.
8. Record the symptoms, actions, tests and any backlog data that still needs to be synced.

Safety rule: do NOT suggest that the assistant itself can disable the plugin, change a token or run a deploy. Authorization and action belong to humans.
