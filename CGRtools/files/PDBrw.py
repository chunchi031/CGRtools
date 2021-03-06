# -*- coding: utf-8 -*-
#
#  Copyright 2020 Ramil Nugmanov <nougmanoff@protonmail.com>
#  This file is part of CGRtools.
#
#  CGRtools is free software; you can redistribute it and/or modify
#  it under the terms of the GNU Lesser General Public License as published by
#  the Free Software Foundation; either version 3 of the License, or
#  (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
#  GNU Lesser General Public License for more details.
#
#  You should have received a copy of the GNU Lesser General Public License
#  along with this program; if not, see <https://www.gnu.org/licenses/>.
#
from io import StringIO, TextIOWrapper
from logging import warning
from pathlib import Path
from traceback import format_exc
from typing import List, Iterable, Tuple, Optional
from .XYZrw import XYZ
from ..containers import MoleculeContainer


one_symbol_names = {'ALA', 'CYS', 'ASP', 'GLU', 'PHE', 'GLY', 'HIS', 'ILE', 'LYS', 'LEU', 'MET', 'ASN', 'PRO', 'GLN', 'ARG',
                    'SER', 'THR', 'VAL', 'TRP', 'TYR',  # Amino acids
                    'ASH',  # H-asparagine
                    'DA', 'DC', 'DG', 'DT', 'DI',  # Deoxyribonucleotides
                    'A', 'C', 'G', 'U', 'I',  # Ribonucleotides
                    'IOD', 'K'}  # Elements
two_symbol_names = {'CL', 'BR', 'NA', 'CA', 'MG', 'CO', 'MN', 'FE', 'CU', 'ZN'}


class PDBRead(XYZ):
    """PDB files reader. Works similar to opened file object. Support `with` context manager.
    On initialization accept opened in text mode file, string path to file,
    pathlib.Path object or another buffered reader object.

    Supported multiple structures in same file separated by ENDMDL. Supported only ATOM and HETATM parsing.
    END or ENDMDL required in the end.
    """
    def __init__(self, file, ignore=False, element_name_priority=False, parse_as_single=False, **kwargs):
        """
        :param ignore: Skip some checks of data or try to fix some errors.
        :param element_name_priority: For ligands use element symbol column value and ignore atom name column.
        :param parse_as_single: Usable if all models in file is the same structure. 2d graph will be restored from first
            model. Other models will be returned as conformers.
        """
        if isinstance(file, str):
            self.__file = open(file)
            self.__is_buffer = False
        elif isinstance(file, Path):
            self.__file = file.open()
            self.__is_buffer = False
        elif isinstance(file, (TextIOWrapper, StringIO)):
            self.__file = file
            self.__is_buffer = True
        else:
            raise TypeError('invalid file. TextIOWrapper, StringIO subclasses possible')
        super().__init__(**kwargs)
        self.__ignore = ignore
        self.__element_name_priority = element_name_priority
        self.__parse_as_single = parse_as_single
        self.__parsed_first = None
        self._data = self.__reader()

    def close(self, force=False):
        """
        Close opened file

        :param force: Force closing of externally opened file or buffer
        """
        if not self.__is_buffer or force:
            self.__file.close()

    def __enter__(self):
        return self

    def __exit__(self, _type, value, traceback):
        self.close()

    def read(self) -> List[MoleculeContainer]:
        """
        Parse whole file

        :return: list of parsed molecules
        """
        return list(iter(self))

    def __iter__(self):
        return (x for x in self._data if x is not None)

    def __next__(self):
        return next(iter(self))

    def __reader(self):
        element_name_priority = self.__element_name_priority
        ignore = self.__ignore
        failkey = False
        atoms = []
        for n, line in enumerate(self.__file):
            if failkey:
                if line.startswith('ENDMDL'):
                    failkey = False
            elif line.startswith(('ATOM', 'HETATM')):
                # COLUMNS        DATA  TYPE    FIELD        DEFINITION
                # -------------------------------------------------------------------------------------
                #  1 -  6        Record name   "ATOM  " or "HETATM"
                #  7 - 11        Integer       serial       Atom  serial number.
                # 13 - 16        Atom          name         Atom name.
                # 17             Character     altLoc       Alternate location indicator.
                # 18 - 20        Residue name  resName      Residue name.
                # 22             Character     chainID      Chain identifier.
                # 23 - 26        Integer       resSeq       Residue sequence number.
                # 27             AChar         iCode        Code for insertion of residues.
                # 31 - 38        Real(8.3)     x            Orthogonal coordinates for X in Angstroms.
                # 39 - 46        Real(8.3)     y            Orthogonal coordinates for Y in Angstroms.
                # 47 - 54        Real(8.3)     z            Orthogonal coordinates for Z in Angstroms.
                # 55 - 60        Real(6.2)     occupancy    Occupancy.
                # 61 - 66        Real(6.2)     tempFactor   Temperature  factor.
                # 77 - 78        LString(2)    element      Element symbol, right-justified.
                # 79 - 80        LString(2)    charge       Charge  on the atom.
                charge = line[78:80].strip()
                if charge:
                    try:
                        charge = int(charge)
                    except ValueError:
                        warning(f'Line [{n}] {line}: consist errors:\n{format_exc()}')
                        failkey = True
                        atoms = []
                        yield None
                else:
                    charge = None
                try:
                    x, y, z = float(line[30:38]), float(line[38:46]), float(line[46:54])
                except ValueError:
                    warning(f'Line [{n}] {line}: consist errors:\n{format_exc()}')
                    failkey = True
                    atoms = []
                    yield None
                    continue

                element = line[76:78].strip()
                residue = line[17:20].strip()
                atom_name = line[12:16].strip(' 0123456789')
                if residue in one_symbol_names:  # bio-polymers and I
                    atom_name = atom_name[0]
                elif residue in two_symbol_names:
                    atom_name = atom_name[:2].capitalize()
                elif residue == 'MSE':
                    if atom_name.startswith('SE'):
                        atom_name = 'Se'
                    else:
                        atom_name = atom_name[0]
                elif residue == 'CBR':
                    if atom_name.startswith('BR'):
                        atom_name = 'Br'
                    else:
                        atom_name = atom_name[0]
                # ligands    
                elif element_name_priority:
                    atom_name = element
                else:
                    atom_name = atom_name.capitalize()

                if atom_name != element:
                    warning(f'Atom name and Element symbol not equal: {line[:-1]}')
                    if not ignore:
                        failkey = True
                        atoms = []
                        yield None
                        continue
                atoms.append((atom_name, charge, x, y, z, residue))
            elif line.startswith('END'):  # EOF or end of complex
                if atoms:  # convert collected atoms
                    try:
                        yield self._convert_structure(atoms)
                    except ValueError:
                        warning(f'Structure consist errors:\n{format_exc()}')
                        yield None
                    atoms = []
                else:
                    warning(f'Line [{n}] {line}: END or ENDMDL before ATOM or HETATM')
                    yield None
        if atoms:  # ENDMDL or END not found
            warning('PDB not finished')
            yield None

    def _convert_structure(self, matrix: Iterable[Tuple[str, Optional[int], float, float, float, str]]):
        if self.__parsed_first is None:
            mol = super()._convert_structure([(e, c, x, y, z) for e, c, x, y, z, _ in matrix])
            mol.meta['RESIDUE'] = {n: x[-1] for n, x in zip(mol, matrix)}
            if self.__parse_as_single:
                self.__parsed_first = [(n, a.atomic_symbol) for n, a in mol.atoms()]
            return mol
        else:
            if len(self.__parsed_first) != len(matrix):
                raise ValueError('models not equal')
            c = {}
            for (n, a), (e, _, x, y, z, _) in zip(self.__parsed_first, matrix):
                if a != e:
                    raise ValueError('models or atom order not equal')
                c[n] = (x, y, z)
            return c


__all__ = ['PDBRead']
