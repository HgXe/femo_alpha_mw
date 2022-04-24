"""
The FEniCS wrapper for the variational forms and the partial derivatives computation
"""

from fea_utils_dolfinx import *
from dolfinx.io import XDMFFile
import ufl

from dolfinx.fem.petsc import (apply_lifting)
from dolfinx.fem import (set_bc, Function, FunctionSpace, dirichletbc,   
                        locate_dofs_topological, locate_dofs_geometrical)
from dolfinx.mesh import compute_boundary_facets
from ufl import (TestFunction, TrialFunction, dx, inner, derivative,
                    grad, SpatialCoordinate)
import matplotlib.pyplot as plt
from scipy.sparse import csr_matrix

PI = np.pi
ALPHA = 1E-6


def pdeRes(u,v,f):
    """
    The variational form of the PDE residual for the Poisson's problem
    """
    return (inner(grad(u),grad(v))-f*v)*dx


class FEA(object):
    """
    The class of the FEniCS wrapper for the motor problem,
    with methods to compute the variational forms, partial derivatives,
    and solve the nonlinear/linear subproblems.
    """
    def __init__(self, mesh, coords_bc=[]):

        self.mesh = mesh
        # # Import the initial mesh from the mesh file to FEniCS
        # self.initMesh()
        # Define the function spaces based on the initial mesh
        self.initFunctionSpace()

        # Get the indices of the vertices that would move during optimization
        # self.bc_ind = self.locateBC(coords_bc)

        self.u = Function(self.V) # Function for the solution of the magnetic vector potential
        self.v = TestFunction(self.V)
        self.dR = Function(self.V) # Function used in the CSDL model
        self.du = Function(self.V) # Function used in the CSDL model
        
        self.f = Function(self.VF)
        self.df = Function(self.VF)
        self.u_ex, self.f_ex = self.exactSolution()
        # self.total_dofs_bc = len(self.bc_ind)
        self.total_dofs_u = len(self.u.vector.getArray())
        self.total_dofs_f = len(self.f.vector.getArray())
        # Partial derivatives in the magnetostatic problem
        self.dR_du = derivative(self.R(), self.u)
        self.dR_df = derivative(self.R(), self.f)
        self.dC_du = derivative(self.objective(), self.u)
        self.dC_df = derivative(self.objective(), self.f)
        
        x = SpatialCoordinate(self.mesh)
        expression = x[1]+x[0]
        f_expression = dolfinx.fem.Expression(expression, self.VF.element.interpolation_points)
        f_init = Function(self.VF)
        f_init.interpolate(f_expression)
        self.initial_guess_f = f_init


    def initFunctionSpace(self):
        """
        Preprocessor 2 to define the function spaces for the mesh motion (VHAT)
        and the problem solution (V)
        """
        self.V = FunctionSpace(self.mesh, ('CG', 1))
        self.VF = FunctionSpace(self.mesh, ('DG', 0))

    # def locateBC(self,coords_bc):
    #     """
    #     Find the indices of the dofs for setting up the boundary condition
    #     in the mesh motion subproblem
    #     """
    #     V0 = FunctionSpace(self.mesh, 'CG', 1)
    #     coordinates = V0.tabulate_dof_coordinates()

    #     # Use KDTree to find the node indices of the points on the edge
    #     # in the mesh object in FEniCS
    #     node_indices = findNodeIndices(np.reshape(coords_bc, (-1,2)),
    #                                     coordinates)

    #     # Convert the node indices to edge indices, where each node has 2 dofs
    #     dofs = np.empty(2*len(node_indices))
    #     for i in range(len(node_indices)):
    #         dofs[2*i] = 2*node_indices[i]
    #         dofs[2*i+1] = 2*node_indices[i]+1

    #     return dofs.astype('int')

    def R(self):
        """
        Formulation of the magnetostatic problem
        """
        res = pdeRes(
                self.u,self.v,self.f)
        return res

    def bc(self):
        # ubc = Function(self.V)
        # ubc.vector.set(0.0)
        # locate_BC1 = locate_dofs_geometrical((self.V, self.V), 
        #                             lambda x: np.isclose(x[0], 0. ,atol=1e-6))
        # locate_BC2 = locate_dofs_geometrical((self.V, self.V), 
        #                             lambda x: np.isclose(x[0], 1. ,atol=1e-6))
        # locate_BC3 = locate_dofs_geometrical((self.V, self.V), 
        #                             lambda x: np.isclose(x[1], 0. ,atol=1e-6))
        # locate_BC4 = locate_dofs_geometrical((self.V, self.V), 
        #                             lambda x: np.isclose(x[1], 1. ,atol=1e-6))
        # bc = [dirichletbc(ubc, locate_BC1, self.V),
        #         dirichletbc(ubc, locate_BC2, self.V),
        #         dirichletbc(ubc, locate_BC3, self.V),
        #         dirichletbc(ubc, locate_BC4, self.V),]
        # Create facet to cell connectivity required to determine boundary facets
        tdim = self.mesh.topology.dim
        fdim = tdim - 1
        self.mesh.topology.create_connectivity(fdim, tdim)
        boundary_facets = np.flatnonzero(
                            compute_boundary_facets(
                                self.mesh.topology))

        boundary_dofs = locate_dofs_topological(self.V, fdim, boundary_facets)
        ubc = Function(self.V)
        ubc.vector.set(0.0)
        bc = [dirichletbc(ubc, boundary_dofs)]
        return bc

    def exactSolution(self):
        """
        Exact solutions for the problem
        """
        class Expression_f:
            def __init__(self):
                self.alpha = 1e-6

            def eval(self, x):
                return (1/(1+self.alpha*4*np.power(PI,4))*
                        np.sin(PI*x[0])*np.sin(PI*x[1]))

        class Expression_u:
            def __init__(self):
                self.alpha = 1e-6

            def eval(self, x):
                return (1/(2*np.power(PI, 2))*
                        1/(1+self.alpha*4*np.power(PI,4))*
                        np.sin(PI*x[0])*np.sin(PI*x[1]))

        f_analytic = Expression_f()
        f_analytic.alpha = ALPHA
        u_analytic = Expression_u()
        u_analytic.alpha = ALPHA
        f_ex = Function(self.VF)
        u_ex = Function(self.V)
        f_ex.interpolate(f_analytic.eval)
        u_ex.interpolate(u_analytic.eval)
        return u_ex, f_ex

    def objective(self):
#        class Expression_d:
#            def __init__(self):
#                pass
#            def eval(self, x):
#                return (1/(2*np.power(PI, 2))*
#                        np.sin(PI*x[0])*np.sin(PI*x[1]))
#                        
#        d_expression = Expression_d()
#        d = Function(self.V)
#        d.interpolate(d_expression.eval)
#        print(getFuncArray(d))
        x = ufl.SpatialCoordinate(self.mesh)
        expression = 1/(2*ufl.pi**2)*ufl.sin(ufl.pi*x[0])*ufl.sin(ufl.pi*x[1])
        d_expression = dolfinx.fem.Expression(expression, self.V.element.interpolation_points)
        d = Function(self.V)
        d.interpolate(d_expression)
        return 0.5*inner(self.u-d, self.u-d)*dx + ALPHA/2*self.f**2*dx

    def getBCDerivatives(self):
        """
        Compute the derivatives of the PDE residual of the mesh motion
        subproblem wrt the BCs, which is a fixed sparse matrix with "-1"s
        on the entries corresponding to the edge indices.
        """

        row_ind = self.bc_ind
        col_ind = np.arange(self.total_dofs_bc)
        data = -1.0*np.ones(self.total_dofs_bc)
        M = csr_matrix((data, (row_ind, col_ind)),
                        shape=(self.total_dofs_uhat, self.total_dofs_bc))
        return M


    def solve(self, report=False):
        """
        Solve the PDE problem
        """
        if report == True:
            print(80*"=")
            print(" FEA: Solving the PDE problem")
            print(80*"=")
        from timeit import default_timer
        start = default_timer()
        solveNonlinear(self.R(), self.u, self.bc(), report=report)
        stop = default_timer()
        if report == True:
            print("Solve nonlinear finished in ",start-stop, "seconds")


    def solveLinearFwd(self, A, dR):
        """
        solve linear system dR = dR_du (A) * du in DOLFIN type
        """
        setFuncArray(self.dR, dR)

        self.du.vector.set(0.0)

        solveKSP(A, self.du.vector, self.dR.vector)
        self.du.vector.assemble()
        self.du.vector.ghostUpdate()
        return self.du.vector.getArray()

    def solveLinearBwd(self, A, du):
        """
        solve linear system du = dR_du.T (A_T) * dR in DOLFIN type
        """
        setFuncArray(self.du, du)

        self.dR.vector.set(0.0)

        solveKSP(transpose(A), self.dR.vector, self.du.vector)
        self.dR.vector.assemble()
        self.dR.vector.ghostUpdate()
        return self.dR.vector.getArray()

if __name__ == "__main__":
    n = 2
    mesh = createUnitSquareMesh(n)
    fea = FEA(mesh)
    f_ex = fea.f_ex
    u_ex = fea.u_ex

    setFuncArray(fea.f, getFuncArray(f_ex))
    # print(getFuncArray(fea.f))
    # print(fea.mesh.geometry.x)

    with XDMFFile(MPI.COMM_WORLD, "solutions/u.xdmf", "w") as xdmf:
        xdmf.write_mesh(fea.mesh)
        xdmf.write_function(fea.u)
    with XDMFFile(MPI.COMM_WORLD, "solutions/f.xdmf", "w") as xdmf:
        xdmf.write_mesh(fea.mesh)
        xdmf.write_function(fea.f)


    fea.solve(report=False)
    state_error = errorNorm(u_ex, fea.u)
    A = assembleMatrix(fea.dR_du, bcs=fea.bc())
    # A,_ = assembleSystem(fea.dR_du, fea.R(), bcs=fea.bc())
    
    print(convertToDense(A))
    # print(getFuncArray(fea.u))
    # print(getFuncArray(fea.f))
    # print(mesh.geometry.x)
    print("="*40)
    control_error = errorNorm(f_ex, fea.f)
    print("Error in controls:", control_error)
    state_error = errorNorm(u_ex, fea.u)
    print("Error in states:", state_error)
    print("number of controls dofs:", fea.total_dofs_f)
    print("number of states dofs:", fea.total_dofs_u)
    print("="*40)
