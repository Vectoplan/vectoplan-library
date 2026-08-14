# Library authorization boundary

The Apache-licensed service defaults to `OpenSourceAllowAllProvider`: a local
installation can create and edit every family and product variant.

The hosted platform sets:

```text
VECTOPLAN_LIBRARY_AUTHZ_PROVIDER=platform_private.library_rights:create_provider
```

That module lives in the ignored `platform_private/` directory (or in a
separately distributed Python package). A configured provider fails closed when
it cannot be imported. The generic database grant table remains part of the
open schema so platform policy code can enforce family-, user- and
organization-specific grants without forking the product/catalog data model.
