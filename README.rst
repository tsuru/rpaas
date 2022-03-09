Reverse proxy service for tsuru PaaS
====================================

Deprecated in favor of https://github.com/tsuru/rpaas-operator

.. image:: https://travis-ci.org/tsuru/rpaas.png?branch=master
   :target: https://travis-ci.org/tsuru/rpaas

Deploying the API
-----------------

First, let's create an app in tsuru, from the project root, execute the following:

.. highlight: bash

::

    % tsuru app-create rpaas python
    % git remote add tsuru git@remote.sbrubles.com
    % git push tsuru master

The push will return an error telling you that you can't push code before the
app unit is up, wait until your unit is in service, you can check with:


.. highlight: bash

::

    % tsuru app-list

When you get an output like this you can proceed to push.

.. highlight: bash

::

    +-------------+-------------------------+--------------------------------------+
    | Application | Units State Summary     | Address                              |
    +-------------+-------------------------+--------------------------------------+
    | your-app    | 1 of 1 units in-service | your-app.somewhere.com               |
    +-------------+-------------------------+--------------------------------------+

Now if you access our app endpoint at "/" (you can check with `tsuru app-info`
cmd) you should get a 404, which is right, since the API does not respond
through this url.
