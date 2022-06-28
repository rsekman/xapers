import os
import requests

from pybtex.database import Entry

description = "International Standard Book Number (ISBN)"

scan_regex = 'isbn:([0-9]{10}|[0-9]{13})'

def get_key(bib):
    def get_name(p):
        return "".join(p.last_names)
    if 'editor' in bib.persons.keys():
        role = 'editor'
    elif 'author' in bib.persons.keys():
        role = 'author'
    name = get_name(bib.persons[role][0])
    year = bib.fields["year"]
    return f"{name}{year}"

def fetch_bibtex(id):
    url = "https://api.paperpile.com/api/public/convert"

    r = requests.post(url,
                      json={"fromIds": True,
                            "input": id,
                            "targetFormat": "Bibtex"
                           }

                     )
    response = r.json()
    bib = Entry.from_string(response["output"], "bibtex")
    bib.fields["isbn"] = id
    bib.key = get_key(bib)

    return bib.to_string("bibtex")
