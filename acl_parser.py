#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import re
import csv

# TODO / Improvement: Handle subnet / wildcard masks, translate CIDR to mask.
# TODO / Improvement: Add 'src_mask' and 'dst_mask' fields.


def iana_srv_parser(iana_csv, delimiter=','):
    '''
    Besides numeric protocol definitions, Cisco ACLs can contain service names. These names correspond
    to the naming convention used by IANA. This function takes the IANA CSV which can be retrieved from
    https://www.iana.org/assignments/service-names-port-numbers and returns a dictionary with service
    name to protcol type and number mappings.

    :param iana_csv: Path to IANA service name and port number CSV
    :param delimiter: Delimiter to use for CSV file
    :return: Dictionary with service name to protocol mapping
    '''
    iana_srv_mapping = []
    with open(iana_csv) as csv_file:
        csv_rows = csv.DictReader(csv_file, delimiter=delimiter)
        for row in csv_rows:
            if row['Service Name'] and row['Port Number']:
                iana_srv_mapping.append({row['Service Name']: row['Transport Protocol'] + '_' + row['Port Number']})
    iana_srv_mapping = merge_dicts(*iana_srv_mapping)
    return iana_srv_mapping


def merge_dicts(*dicts):
    '''
    Merges dictionaries with duplicate keys. Values are concatenated into a list per key value.

    :param dicts: Dictionaries to be merged
    :return: Dictionary with deduplicated keys
    '''
    d = {}
    for dict in dicts:
        for key in dict:
            try:
                d[key].append(dict[key])
            except KeyError:
                d[key] = [dict[key]]
    return d


def txt_to_list(file_path):
    '''
    Reads each line of a given text file into a list.

    :param file_path: Path to the text file.
    :return: List of lines.
    '''
    with open(file_path, 'r') as f:
        txt_lines = [i.strip() for i in f.readlines()]
    return txt_lines


def value_by_position(input_list, base_object, index_offset=0):
    '''
    Retrieves the value of a given list item by index. By changing the optional offset, the
    value of a positionally relative list item is retrieved.

    :param input_list: List of objects
    :param base_object: Starting point
    :param index_offset: Optional index offset
    :return:
    '''
    value = input_list[input_list.index(base_object) + index_offset]
    return value


def acl_rule_parser(acl_rule):
    '''
    Parses a Cisco ACL rule by assigning rule parameters to predefined categories.
    Rules are sequentially parsed from left to right and category assignment is determined
    by looking at the relative position of other parameters given the type of rule.

    :param acl_rule: String of a single ACL rule
    :return: A parsed ACL rule in list format
    '''

    # Initialize variable default values
    acl_proto, src_ip, src_operator, src_port_begin, src_port_end, dst_ip, \
    dst_operator, dst_port_begin, dst_port_end, acl_state = ('',) * 10
    src_type = dst_type = 'network'

    # Pad the rule to handle variable length of the list
    acl_rule = acl_rule.split()
    acl_rule += [''] * (16 - len(acl_rule))

    # Retrieve the sequence number
    seq_number = acl_rule[0]

    # Retrieve the action
    acl_action = acl_rule[1]
    if acl_action == 'remark':  # If the rule is a remark, parse the remark
        global acl_remark
        acl_remark = ' '.join(acl_rule[2:]).strip()
        src_type = dst_type = ''
    else:  # If the action is permit / deny
        acl_proto = acl_rule[2]  # Retrieve the protocol

        # Handle (source) host entries and retrieve source IP (range)
        if acl_rule[3] == 'host':
            src_ip = acl_rule[4]
            src_type = 'host'
        else:
            src_ip = acl_rule[3]

        # Handle TCP / UDP rules
        if acl_proto == 'tcp' or acl_proto == 'udp':
            # If there is a numeric value after 'src_ip' it is 'dst_ip' implicitly
            if re.search('\d', value_by_position(acl_rule, src_ip, 1)):
                dst_ip = value_by_position(acl_rule, src_ip, 1)
            else:
                # Otherwise the next index in the list is the 'src_operator'
                src_operator = value_by_position(acl_rule, src_ip, 1)
                src_port_begin = value_by_position(acl_rule, src_operator, 1)

                # Handle port ranges
                # TODO: Ranges can now only be numeric. I.e.: 'range nameserver bootp' would fail currently
                if src_operator == 'range' \
                        and (re.search('^\d+$', value_by_position(acl_rule, src_operator, 1)) \
                                     and re.search('^\d+$', value_by_position(acl_rule, src_operator, 2))):
                    # Handle destination types
                    if value_by_position(acl_rule, src_operator, 3) == 'host':
                        src_port_end = value_by_position(acl_rule, src_operator, 2)
                        dst_ip = value_by_position(acl_rule, src_operator, 4)
                        dst_type = 'host'
                    else:
                        src_port_end = value_by_position(acl_rule, src_operator, 2)
                        dst_ip = value_by_position(acl_rule, src_operator, 3)
                else:  # Operators like 'eq', 'gt', 'lt' or a range with only a starting port
                    # Handle destination types
                    if value_by_position(acl_rule, src_operator, 2) == 'host':
                        dst_ip = value_by_position(acl_rule, src_operator, 3)
                        dst_type = 'host'
                    # Ranges can be defined with only a starting value (sadly...)
                    # If the next value contains a dot the range ended early
                    elif re.search('\.', value_by_position(acl_rule, src_operator, 2)):
                        dst_ip = value_by_position(acl_rule, src_operator, 2)
                    # Handle 'any' destination while making sure it doesn't belong to a port range
                    elif value_by_position(acl_rule, src_operator, 2) == 'any' and not \
                            re.search('\.', value_by_position(acl_rule, src_operator, 3)):
                        dst_ip = 'any'

                # Determine destination operator and ports
                if value_by_position(acl_rule, dst_ip, 1):
                    if value_by_position(acl_rule, dst_ip, 1) in ['eq', 'gt', 'lt', 'range']:
                        dst_operator = value_by_position(acl_rule, dst_ip, 1)

                        # Handle destination port (ranges) by reversing the list. Otherwise if 'range' occurs twice,
                        # the second 'range' would match the first occurence index causing it to use the source ports
                        reversed_acl_rule = list(reversed(acl_rule))
                        dst_port_begin = value_by_position(reversed_acl_rule, dst_operator, -1)

                        if dst_operator == 'range' \
                                and (re.search('^\d+$', value_by_position(reversed_acl_rule, dst_operator, -1))
                                     and re.search('^\d+$', value_by_position(reversed_acl_rule, dst_operator, -2))):
                            dst_port_end = value_by_position(reversed_acl_rule, dst_operator, -2)

            # Check for ACL state with an iterator (due to the padding)
            if next(x for x in reversed(acl_rule) if x is not '') == 'established':
                acl_state = 'established'

            # Map service names to correct protocol numbers
            port_mapping = []
            for srv_identifier in [src_port_begin, src_port_end, dst_port_begin, dst_port_end]:
                # netbios-ss should have been netbios-ssn in Cisco code...
                if srv_identifier == 'netbios-ss':
                    srv_identifier = 'netbios-ssn'

                # Revert the IANA port number to name mapping
                if re.search('[a-z]', srv_identifier):
                    # Get the mapping for the correct protocol
                    srv_identifier = [x for x in iana_srv_mapping[srv_identifier] if acl_proto in x]
                    # Take only the numeric portion
                    srv_identifier = ''.join(srv_identifier).split('_')[1]
                port_mapping.append(srv_identifier)

            # Rewrite the service mappings
            [src_port_begin, src_port_end, dst_port_begin, dst_port_end] = port_mapping

        else:  # TODO: Increase the amount of handled protocols
            src_ip = acl_rule[3]
            dst_ip = acl_rule[4]

    parsed_rule = [acl_name, acl_remark, seq_number, acl_action, acl_proto, src_type,
                   src_ip, src_operator, src_port_begin, src_port_end, dst_type,
                   dst_ip, dst_operator, dst_port_begin, dst_port_end, acl_state]

    return parsed_rule


if __name__ == '__main__':
    # Retrieve IANA service mapping
    iana_srv_mapping = iana_srv_parser('iana_srv_name_and_port.csv')

    # Insert CSV header
    parsed_acl = [['acl_name', 'acl_remark', 'seq_number', 'acl_action', 'acl_proto', 'src_type',
                   'src_ip', 'src_operator', 'src_port_begin', 'src_port_end', 'dst_type',
                   'dst_ip', 'dst_operator', 'dst_port_begin', 'dst_port_end', 'acl_state']]

    # Read ACL to a two-dimensional list
    acl_rules = txt_to_list('input.txt')

    # Retrieve the ACL name
    acl_name = ' '.join(acl_rules[0].split()[3:])

    # Create a placeholder for the remark
    acl_remark = ''

    # Parse the ACL rules
    for rule in acl_rules[1:]:
        parsed_acl.append(acl_rule_parser(rule))

    # Write out to CSV file
    with open('output.csv', 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerows(parsed_acl)
