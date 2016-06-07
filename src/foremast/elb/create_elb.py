"""Create ELBs for Spinnaker Pipelines."""
import json
import logging

import requests

from ..consts import API_URL, HEADERS
from ..utils import (check_task, get_subnets, get_template, get_vpc_id,
                     get_properties)
from .format_listeners import format_listeners
from .splay_health import splay_health


class SpinnakerELB:
    """Create ELBs for Spinnaker."""

    log = logging.getLogger(__name__)

    def __init__(self, app=None, env=None, region=None, prop_path=None):
        self.app = app
        self.env = env
        self.region = region
        self.properties = get_properties(
            properties_file=prop_path,
            env=self.env)

    def make_elb_json(self):
        """Render the JSON template with arguments.

        Returns:
            str: Rendered ELB template.
        """
        env = self.env
        region = self.region
        elb_settings = self.properties['elb']
        health_settings = elb_settings['health']

        region_subnets = get_subnets(target='elb', env=env, region=region)

        # CAVEAT: Setting the ELB to public, you must use a public subnet,
        #         otherwise AWS complains about missing IGW on subnet.

        elb_subnet_purpose = elb_settings.get('subnet_purpose', 'internal')

        if elb_subnet_purpose == 'internal':
            is_internal = 'true'
        else:
            is_internal = 'false'

        target = elb_settings.get('target', 'HTTP:80/health')
        health = splay_health(target)

        listeners = format_listeners(elb_settings=elb_settings,
                                     env=self.env)

        security_groups = [
            'sg_apps',
            self.app,
        ]
        security_groups.extend(self.properties['security_group']['elb_extras'])

        template_kwargs = {
            'app_name': self.app,
            'availability_zones': json.dumps(region_subnets),
            'env': env,
            'hc_string': target,
            'health_interval': health_settings['interval'],
            'health_path': health.path,
            'health_port': health.port,
            'health_protocol': health.proto,
            'health_timeout': health_settings['timeout'],
            'healthy_threshold': health_settings['threshold'],
            'isInternal': is_internal,
            'listeners': json.dumps(listeners),
            'region_zones': json.dumps(region_subnets[region]),
            'region': region,
            'security_groups': json.dumps(security_groups),
            'subnet_type': elb_subnet_purpose,
            'unhealthy_threshold': health_settings['unhealthy_threshold'],
            'vpc_id': get_vpc_id(env, region),
        }

        rendered_template = get_template(
            template_file='elb_data_template.json',
            **template_kwargs)

        return rendered_template

    def create_elb(self):
        """Create/Update ELB.

        Args:
            json_data: elb json payload.
            app: application name related to this ELB.

        Returns:
            task id to track the elb creation status.
        """
        app = self.app
        json_data = self.make_elb_json()

        url = API_URL + '/applications/%s/tasks' % app
        response = requests.post(url, data=json_data, headers=HEADERS)

        assert response.ok, 'Error creating {0} ELB: {1}'.format(app,
                                                                 response.text)

        taskid = response.json()
        assert check_task(taskid, app)
