1.0.14 (2017-08-08)
-------------------

- b/w compat OPTIONS call for getting auth code
  [vangheem]


1.0.13 (2017-08-07)
-------------------

- override OPTIONS for @oauthgetcode
  [vangheem]


1.0.12 (2017-08-04)
-------------------

- Detect invalid service tokens and refresh
  [vangheem]


1.0.11 (2017-08-04)
-------------------

- More logging


1.0.10 (2017-08-04)
-------------------

- Log correct service token
  [vangheem]


1.0.9 (2017-08-04)
------------------

- More logging
  [vangheem]


1.0.8 (2017-08-04)
------------------

- Handle errors better on renewing service tokens
  [vangheem]


1.0.7 (2017-07-24)
------------------

- Allow user to validate without any roles from api
  [vangheem]


1.0.6 (2017-07-24)
------------------

- Fix use of OPTIONS for oauth endpoint
  [vangheem]

- make sure POST request pushes variables to oauth endpoint as json data
  [vangheem]


1.0.5 (2017-07-24)
------------------

- @oauthgetcode now works on application root as well as container
  [vangheem]


1.0.4 (2017-06-25)
------------------

- User id on oauth may not be mail
  [bloodbare]

1.0.3 (2017-06-16)
------------------

- Handle oauth errors on connecting to invalid server
  [vangheem]


1.0.2 (2017-06-16)
------------------

- Handle errors when no config is provided
  [vangheem]


1.0.1 (2017-06-15)
------------------

- Do not raise KeyError if user is not found, raise Unauthorized
  [vangheem]


1.0.0 (2017-04-24)
------------------

- initial release
