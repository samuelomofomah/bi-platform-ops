Drop `.twb` / `.twbx` files here. On merge to `main`, the `promote` job in
`.github/workflows/ci.yml` publishes each one to the Tableau project named in
the `TABLEAU_PROJECT` repository variable (overwrite mode).
